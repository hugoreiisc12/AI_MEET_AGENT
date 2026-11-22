"""Chamada ao modelo de linguagem, sem LangChain (ADR-014).

- Ollama: API nativa, com `num_ctx` explícito (sem ele o Ollama corta o prompt em 4096 tokens
  sem avisar, ADR-010) e SEMPRE O MESMO: trocar a janela entre pedidos faz o Ollama recarregar o
  modelo e reler o prompt inteiro (medido: 47-52 s contra 2-3 s com o prompt em cache, ADR-021).
- OpenAI e OpenRouter: SDK oficial `openai` (OpenRouter fala o mesmo protocolo). `OPENAI_BASE_URL`
  aponta para qualquer servidor compatível (vLLM, LM Studio, Groq...).

O `ModelProfile` (ADR-022) diz o que o modelo sabe fazer; o grafo do agente é o mesmo para todos:
sem chamada de ferramenta nativa, a ferramenta vem por JSON; sem modo JSON, o JSON vem pelo texto.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Optional

import requests

from config.settings import get_settings
from domain.interfaces.llm_service import LLMServiceError
from infrastructure.observability import timed

NUM_PREDICT = 2000
CHARS_PER_TOKEN = 2.4  # ~2,6 medido em português (ADR-010); 2,4 dá folga
HOSTED_WINDOW = 128000  # OpenAI e OpenRouter, quando LLM_CONTEXT_TOKENS não diz outra coisa


@dataclass(frozen=True)
class ModelProfile:
    provider: str
    model: str
    context_tokens: int   # janela inteira: prompt + resposta
    native_tools: bool    # o provider devolve tool_calls
    json_mode: bool       # o provider força a saída em JSON


def build_profile(s) -> ModelProfile:
    provider = s.llm_provider
    if provider == "ollama" or (provider == "openai" and not s.openai_api_key.strip()
                                and not getattr(s, "openai_base_url", "")):
        provider = "ollama"  # OpenAI sem chave cai no Ollama local, como antes.
    model = {"ollama": s.ollama_model, "openrouter": getattr(s, "openrouter_model", "")}.get(
        provider, getattr(s, "openai_model", ""))
    window = getattr(s, "llm_context_tokens", 0) or (s.ollama_num_ctx_max if provider == "ollama" else HOSTED_WINDOW)
    return ModelProfile(provider, model, window, getattr(s, "llm_native_tools", True), getattr(s, "llm_json_mode", True))


@dataclass(frozen=True)
class ContextBudget:
    """Quanto da conversa cabe no pedido (S12-5). O prompt vai na ordem do que menos muda ao que mais
    muda: contrato e regras, reunião aberta, conversa, e só então o que é desta pergunta (trechos,
    outras reuniões, a pergunta). Assim o Ollama reaproveita o prefixo em cache entre perguntas.
    Se não couber, saem as mensagens mais antigas da conversa; o resto tem teto próprio na origem
    (LLM_CONTEXT_CHARS, EXCERPT_CHARS, meeting_memory.MAX_CHARS)."""
    window_tokens: int
    reply_tokens: int = NUM_PREDICT

    def fit_history(self, history: list[dict], *fixed: str) -> list[dict]:
        room = int((self.window_tokens - self.reply_tokens) * CHARS_PER_TOKEN) - sum(map(len, fixed))
        kept: list[dict] = []
        for message in reversed(history):
            room -= len(message["content"])
            if room < 0:
                break
            kept.append(message)
        return kept[::-1]


class ModelClient:
    def __init__(self, settings=None) -> None:
        self._s = settings or get_settings()
        self._openai = None
        self.profile = build_profile(self._s)
        self.ollama = self.profile.provider == "ollama"
        self._provider = self.profile.provider

    def complete(self, messages: list[dict], as_json: bool = False) -> str:
        try:
            with timed("llm_seconds", {"kind": "json" if as_json else "text", "provider": self._provider}):
                return self._ollama(messages, as_json) if self.ollama else self._compatible(messages, as_json)
        except LLMServiceError:
            raise
        except Exception as exc:
            raise LLMServiceError(f"Falha ao chamar o modelo: {exc}") from exc

    def complete_tools(self, messages: list[dict], tools: list[dict]) -> tuple[str, Optional[dict]]:
        """Resposta em texto ou o pedido de UMA ferramenta: (texto, {"name", "arguments"} | None).
        `tools` no formato de função da OpenAI, que o Ollama também aceita."""
        if not self.profile.native_tools:
            return self._tools_by_json(messages, tools)
        with timed("llm_seconds", {"kind": "tools", "provider": self._provider}):
            return self._complete_tools(messages, tools)

    def complete_tools_stream(self, messages: list[dict], tools: list[dict],
                              on_delta: Callable[[str], None]) -> tuple[str, Optional[dict]]:
        """Como complete_tools, mas o texto sai aos pedaços em `on_delta` enquanto o modelo escreve
        (S16-2, proposta da ADR-021). Sem ferramenta nativa, a saída é JSON: aí não há o que mostrar
        aos pedaços e o pedido vai inteiro."""
        if not self.profile.native_tools:
            return self.complete_tools(messages, tools)
        try:
            with timed("llm_seconds", {"kind": "stream", "provider": self._provider}):
                if self.ollama:
                    return self._ollama_stream(messages, tools, on_delta)
                return self._compatible_stream(messages, tools, on_delta)
        except LLMServiceError:
            raise
        except Exception as exc:
            raise LLMServiceError(f"Falha ao chamar o modelo: {exc}") from exc

    def _ollama_stream(self, messages, tools, on_delta) -> tuple[str, Optional[dict]]:
        payload = self._ollama_payload(messages, as_json=False, tools=tools)
        payload["stream"] = True
        base = self._s.ollama_base_url.rstrip("/").removesuffix("/v1")
        text, call = [], None
        with requests.post(f"{base}/api/chat", json=payload, timeout=600, stream=True) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                part = json.loads(line)
                message = part.get("message") or {}
                if message.get("tool_calls"):
                    fn = message["tool_calls"][0]["function"]
                    args = fn.get("arguments")
                    call = {"name": fn["name"], "arguments": json.loads(args) if isinstance(args, str) else args or {}}
                if message.get("content"):
                    text.append(message["content"])
                    if call is None:
                        on_delta(message["content"])
                if part.get("done"):
                    self.last_usage = {k: part.get(k) for k in ("prompt_eval_count", "prompt_eval_duration", "eval_count")}
        return "".join(text), call

    def _compatible_stream(self, messages, tools, on_delta) -> tuple[str, Optional[dict]]:
        self._ensure_openai()
        stream = self._openai.chat.completions.create(model=self._model, messages=messages, temperature=0.2,
                                                      tools=tools, stream=True)
        text, name, args = [], None, []
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            for tc in delta.tool_calls or []:  # a chamada chega em pedaços: nome uma vez, argumentos aos poucos
                name = name or (tc.function.name if tc.function else None)
                args.append((tc.function.arguments or "") if tc.function else "")
            if delta.content:
                text.append(delta.content)
                if name is None:
                    on_delta(delta.content)
        call = {"name": name, "arguments": json.loads("".join(args) or "{}")} if name else None
        return "".join(text), call

    def _tools_by_json(self, messages: list[dict], tools: list[dict]) -> tuple[str, Optional[dict]]:
        """Modelo sem ferramenta nativa: descreve as ferramentas no prompt e lê a escolha num JSON.
        Saída fora do formato vale como resposta em texto (a verificação do contrato vem depois)."""
        specs = [t["function"] for t in tools]
        guide = ("FERRAMENTAS (este modelo as chama por JSON). Responda APENAS com um objeto JSON, num destes "
                 'formatos: {"answer": "sua resposta em texto"} ou {"tool": {"name": "<nome>", "arguments": {...}}}. '
                 "Ferramentas disponíveis:\n" + json.dumps(specs, ensure_ascii=False))
        first, rest = messages[0], messages[1:]
        if first["role"] == "system":
            messages = [{**first, "content": f"{first['content']}\n\n{guide}"}, *rest]
        else:
            messages = [{"role": "system", "content": guide}, *messages]
        raw = self.complete(messages, as_json=True)
        return parse_tool_json(raw, {s["name"] for s in specs})

    def _complete_tools(self, messages: list[dict], tools: list[dict]) -> tuple[str, Optional[dict]]:
        try:
            if self.ollama:
                message = self._ollama_message(messages, as_json=False, tools=tools)
                calls = message.get("tool_calls") or []
                call = calls[0]["function"] if calls else None
                if call and isinstance(call.get("arguments"), str):
                    call = {**call, "arguments": json.loads(call["arguments"])}
                return message.get("content") or "", call and {"name": call["name"], "arguments": call["arguments"]}
            self._ensure_openai()
            resp = self._openai.chat.completions.create(model=self._model, messages=messages, temperature=0.2,
                                                         tools=tools)
            message = resp.choices[0].message
            if message.tool_calls:
                fn = message.tool_calls[0].function
                return message.content or "", {"name": fn.name, "arguments": json.loads(fn.arguments or "{}")}
            return message.content or "", None
        except LLMServiceError:
            raise
        except Exception as exc:
            raise LLMServiceError(f"Falha ao chamar o modelo: {exc}") from exc

    def _ollama(self, messages: list[dict], as_json: bool) -> str:
        return self._ollama_message(messages, as_json)["content"]

    def _ollama_message(self, messages: list[dict], as_json: bool, tools: Optional[list[dict]] = None) -> dict:
        payload = self._ollama_payload(messages, as_json, tools)
        base = self._s.ollama_base_url.rstrip("/").removesuffix("/v1")
        resp = requests.post(f"{base}/api/chat", json=payload, timeout=600)
        resp.raise_for_status()
        body = resp.json()
        # prompt_eval_count = tokens do prompt (o Ollama 0.24 conta também os que vieram do cache).
        self.last_usage = {k: body.get(k) for k in ("prompt_eval_count", "prompt_eval_duration", "eval_count")}
        return body["message"]

    def _ollama_payload(self, messages: list[dict], as_json: bool, tools: Optional[list[dict]] = None) -> dict:
        # As ferramentas também ocupam a janela.
        chars = sum(len(m["content"]) for m in messages) + (len(json.dumps(tools)) if tools else 0)
        needed = int(chars / CHARS_PER_TOKEN) + NUM_PREDICT
        if needed > self._s.ollama_num_ctx_max:
            raise LLMServiceError(
                f"Contexto de ~{needed} tokens excede o limite configurado "
                f"({self._s.ollama_num_ctx_max}). Reduza LLM_CONTEXT_CHARS ou aumente OLLAMA_NUM_CTX_MAX."
            )
        # Janela fixa: o contrato (início do prompt, igual em todo pedido) fica no cache do Ollama.
        num_ctx = self._s.ollama_num_ctx_max
        payload = {
            "model": self._s.ollama_model,
            "messages": messages,
            "stream": False,
            # Modelo carregado entre perguntas espaçadas (o padrão do Ollama descarrega em 5 min).
            "keep_alive": self._s.ollama_keep_alive,
            "options": {"num_predict": NUM_PREDICT, "temperature": 0.1, "num_ctx": num_ctx},
        }
        if as_json:
            payload["format"] = "json"
        if tools:
            payload["tools"] = tools
        return payload

    def _compatible(self, messages: list[dict], as_json: bool) -> str:
        self._ensure_openai()
        extra: dict = {"response_format": {"type": "json_object"}} if as_json and self.profile.json_mode else {}
        resp = self._openai.chat.completions.create(model=self._model, messages=messages, temperature=0.2, **extra)
        return resp.choices[0].message.content or ""

    def _ensure_openai(self) -> None:
        if self._openai is None:
            from openai import OpenAI
            if self._s.llm_provider == "openrouter":
                self._openai = OpenAI(
                    api_key=self._s.openrouter_api_key, base_url="https://openrouter.ai/api/v1",
                    default_headers={"HTTP-Referer": self._s.openrouter_site_url, "X-Title": self._s.openrouter_site_name},
                )
                self._model = self._s.openrouter_model
            else:
                self._openai = OpenAI(api_key=self._s.openai_api_key or "none",
                                      base_url=getattr(self._s, "openai_base_url", "") or None)
                self._model = self._s.openai_model


def parse_tool_json(raw: str, names: set[str]) -> tuple[str, Optional[dict]]:
    """(texto, ferramenta) a partir do JSON de um modelo sem ferramenta nativa."""
    cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return raw.strip(), None
    if not isinstance(data, dict):
        return raw.strip(), None
    tool = data.get("tool")
    if isinstance(tool, dict) and tool.get("name") in names:
        args = tool.get("arguments")
        return "", {"name": tool["name"], "arguments": args if isinstance(args, dict) else {}}
    answer = data.get("answer")
    return (answer.strip() if isinstance(answer, str) else raw.strip()), None
