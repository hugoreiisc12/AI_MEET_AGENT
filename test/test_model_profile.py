"""Harness adaptável (ADR-022, S12-1/2/5): perfil do modelo, ferramenta por JSON e orçamento."""
from types import SimpleNamespace

from infrastructure.llm.meeting_agent import TOOLS, MeetingAgent
from infrastructure.llm.model_client import ContextBudget, ModelClient, build_profile, parse_tool_json


def cfg(**kw):
    base = dict(llm_provider="ollama", openai_api_key="", ollama_num_ctx_max=32768, ollama_model="qwen",
                openai_model="gpt", openrouter_model="or", llm_context_tokens=0, llm_native_tools=True,
                llm_json_mode=True, openai_base_url="", ollama_keep_alive="30m", ollama_base_url="http://h:11434/v1")
    return SimpleNamespace(**{**base, **kw})


def test_perfil_vem_do_env():
    assert build_profile(cfg()).context_tokens == 32768 and build_profile(cfg()).model == "qwen"
    hosted = build_profile(cfg(llm_provider="openrouter"))
    assert (hosted.provider, hosted.model, hosted.context_tokens) == ("openrouter", "or", 128000)
    assert build_profile(cfg(llm_provider="openai")).provider == "ollama"  # sem chave: Ollama local
    compat = build_profile(cfg(llm_provider="openai", openai_base_url="http://vllm:8000/v1", llm_context_tokens=8192))
    assert (compat.provider, compat.context_tokens) == ("openai", 8192)


def test_ferramenta_por_json():
    names = {"send_email", "create_document"}
    assert parse_tool_json('{"tool": {"name": "create_document", "arguments": {"format": "pdf"}}}', names) == \
        ("", {"name": "create_document", "arguments": {"format": "pdf"}})
    assert parse_tool_json('```json\n{"answer": "Carla envia na sexta."}\n```', names) == ("Carla envia na sexta.", None)
    assert parse_tool_json('{"tool": {"name": "apagar_tudo"}}', names)[1] is None  # ferramenta que não existe
    assert parse_tool_json("Texto solto, fora do formato.", names) == ("Texto solto, fora do formato.", None)


def test_modelo_sem_ferramenta_nativa_pede_json(monkeypatch):
    client = ModelClient(cfg(llm_native_tools=False))
    seen = {}

    def fake_complete(messages, as_json=False):
        seen.update(messages=messages, as_json=as_json)
        return '{"answer": "ok"}'
    monkeypatch.setattr(client, "complete", fake_complete)
    assert client.complete_tools([{"role": "system", "content": "C"}, {"role": "user", "content": "P"}], TOOLS) == ("ok", None)
    assert seen["as_json"] and "send_email" in seen["messages"][0]["content"] and len(seen["messages"]) == 2


def test_orcamento_tira_a_conversa_mais_antiga():
    budget = ContextBudget(window_tokens=1000, reply_tokens=500)  # 1200 caracteres livres
    history = [{"role": "user", "content": "a" * 500}, {"role": "assistant", "content": "b" * 500},
               {"role": "user", "content": "c" * 500}]
    assert [m["content"][0] for m in budget.fit_history(history, "x" * 100)] == ["b", "c"]
    assert budget.fit_history(history, "x" * 1300) == []


class SpyModel:
    profile = SimpleNamespace(context_tokens=32768)

    def __init__(self):
        self.calls = []

    def complete_tools(self, messages, tools):
        self.calls.append(messages)
        return "Ana confirmou.", None


def test_prefixo_igual_entre_perguntas():
    """O que é da pergunta vai na mensagem dela; o prompt de sistema não muda (cache do Ollama)."""
    model = SpyModel()
    agent = MeetingAgent(model=model, contract="CONTRATO")
    agent.chat("primeira?", context="[00:01] Ana: ok", history=[], question_context="TRECHO-1\n")
    agent.chat("segunda?", context="[00:01] Ana: ok", history=[], question_context="TRECHO-2\n")
    first, second = model.calls
    assert first[0] == second[0] and "TRECHO" not in first[0]["content"]
    assert first[-1]["content"] == "TRECHO-1\n\nPERGUNTA: primeira?"


def test_ollama_em_streaming_entrega_pedacos_e_ferramenta(monkeypatch):
    import json as _json
    import requests
    lines = [{"message": {"content": "Ana "}}, {"message": {"content": "confirmou."}},
             {"message": {"content": ""}, "done": True, "prompt_eval_count": 10}]

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def raise_for_status(self): pass
        def iter_lines(self): return [_json.dumps(x).encode() for x in self.lines]
    resp = Resp()
    resp.lines = lines
    monkeypatch.setattr(requests, "post", lambda url, json, timeout, stream: resp)
    client = ModelClient(cfg())
    pieces = []
    assert client.complete_tools_stream([{"role": "user", "content": "oi"}], TOOLS, pieces.append) == ("Ana confirmou.", None)
    assert pieces == ["Ana ", "confirmou."] and client.last_usage["prompt_eval_count"] == 10
    resp.lines = [{"message": {"content": "", "tool_calls": [{"function": {"name": "remember", "arguments": {"note": "x"}}}]}},
                  {"message": {"content": ""}, "done": True}]
    pieces.clear()
    assert client.complete_tools_stream([{"role": "user", "content": "oi"}], TOOLS, pieces.append)[1]["name"] == "remember"
    assert pieces == []


def test_agente_transmite_so_a_primeira_tentativa():
    class Model:
        profile = SimpleNamespace(context_tokens=32768)
        def __init__(self): self.answers = ['Ana disse: "frase que ninguém falou na reunião".', "Ana confirmou."]
        def complete_tools_stream(self, messages, tools, on_delta):
            text = self.answers.pop(0)
            on_delta(text)
            return text, None
        def complete_tools(self, messages, tools):
            return self.answers.pop(0), None
    pieces = []
    reply = MeetingAgent(model=Model(), contract="C").chat("a Ana confirmou?", context="[00:01] Ana: confirmo",
                                                          history=[], on_delta=pieces.append)
    assert len(pieces) == 1 and reply.answer == "Ana confirmou."  # a reprovada saiu aos pedaços; vale a corrigida


def test_tetos_dos_blocos_acompanham_a_janela():
    from use_cases.chat_with_meeting import CROSS_CHARS, EXCERPT_CHARS, ChatWithMeetingUC
    floor = ChatWithMeetingUC(None, window_chars=int((32768 - 2000) * 2.4))
    assert (floor._excerpt_chars, floor._cross_chars) == (EXCERPT_CHARS, CROSS_CHARS)  # o piso não muda
    small = ChatWithMeetingUC(None, window_chars=int((8192 - 2000) * 2.4))
    assert small._excerpt_chars < 3000 and small._cross_chars < 1200 and small._records_chars < 1000
