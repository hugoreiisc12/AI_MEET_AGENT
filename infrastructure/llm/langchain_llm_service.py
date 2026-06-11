# Implementação de LLM service usando LangChain para processamento de reuniões
# Suporta OpenAI, Ollama (local) e OpenRouter
import json
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, BaseMessage
from pydantic import SecretStr

from domain.entities.meeting import Summary, Task, Decision
from domain.entities.meeting_type import MeetingType
from interface.llm_services import ILLMService, LLMServiceError
from config.settings import get_settings
from infrastructure.llm.prompt_builder import PromptBuilder

CHAT_SYSTEM_PROMPT = """Você é um assistente de reuniões. Você participou da reunião abaixo e pode responder perguntas sobre ela.

TRANSCRIÇÃO DA REUNIÃO:
{transcript}

CONTRATO — REGRAS ABSOLUTAS:
1. Responda SEMPRE em português do Brasil
2. NÃO alucine — responda SOMENTE com base no que foi falado na transcrição
3. Valide ortografia e gramática da sua resposta (corrija erros óbvios)
4. Se a informação não estiver na transcrição, diga exatamente:
   "Isso não foi mencionado durante a reunião."
5. Cite o contexto quando relevante (ex: "Conforme mencionado por [nome]...")
6. Seja direto, objetivo e factual
7. Não adicione opiniões, suposições ou informações externas"""


class LangChainLLMService(ILLMService):
    """Serviço de LLM com LangChain — suporta OpenAI, Ollama e OpenRouter."""

    def __init__(self, llm: ChatOpenAI | None = None) -> None:
        settings = get_settings()
        self._prompt_builder = PromptBuilder()
        self._current_transcript: str = ""

        if llm:
            self._llm = llm

        elif getattr(settings, "llm_provider", "openai") == "ollama":
            self._llm = ChatOpenAI(
                model=getattr(settings, "ollama_model", "nemotron-mini"),
                api_key=SecretStr("ollama"),
                base_url=getattr(settings, "ollama_base_url", "http://localhost:11434/v1"),
                temperature=0.2,
            )

        elif getattr(settings, "llm_provider", "openai") == "openrouter":
            self._llm = ChatOpenAI(
                model=getattr(settings, "openrouter_model", "openai/gpt-4o"),
                api_key=SecretStr(getattr(settings, "openrouter_api_key", "")),
                base_url="https://openrouter.ai/api/v1",
                temperature=0.2,
                default_headers={
                    "HTTP-Referer": getattr(settings, "openrouter_site_url", ""),
                    "X-Title": getattr(settings, "openrouter_site_name", "Meet Agent"),
                },
            )

        else:
            if not settings.openai_api_key or settings.openai_api_key.strip() == "":
                import warnings
                warnings.warn(
                    "OPENAI_API_KEY não configurada. Tentando usar Ollama local...",
                    stacklevel=2,
                )
                self._llm = ChatOpenAI(
                    model=getattr(settings, "ollama_model", "nemotron-mini"),
                    api_key=SecretStr("ollama"),
                    base_url=getattr(settings, "ollama_base_url", "http://localhost:11434/v1"),
                    temperature=0.2,
                )
            else:
                self._llm = ChatOpenAI(
                    model=settings.openai_model,
                    api_key=SecretStr(settings.openai_api_key),
                    temperature=0.2,
                )

    def _call_ollama_summarize(self, system_prompt: str, user_message: str) -> str:
        """Chama Ollama via API nativa (com format=json) para sumarização."""
        import requests as _requests
        settings = get_settings()
        base = getattr(settings, "ollama_base_url", "http://localhost:11434/v1")
        base = base.replace("/v1", "").replace("/v1/", "")
        resp = _requests.post(
            f"{base}/api/chat",
            json={
                "model": getattr(settings, "ollama_model", "nemotron-mini"),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "format": "json",
                "stream": False,
                "options": {"num_predict": 2000, "temperature": 0.1},
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    def summarize(self, transcript: str, meeting_type: MeetingType = MeetingType.GENERAL) -> Summary:
        """Analisa transcrição e retorna Summary com tópicos, tarefas, decisões."""
        try:
            system_prompt = self._prompt_builder.build_summarize_system(meeting_type)
            user_message  = self._prompt_builder.build_summarize_user(transcript)

            from config.settings import get_settings
            _settings = get_settings()
            provider = getattr(_settings, "llm_provider", "openai")

            if provider == "ollama":
                content = self._call_ollama_summarize(system_prompt, user_message)
            else:
                messages: list[BaseMessage] = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_message),
                ]
                response = self._llm.invoke(messages)
                content  = response.content if isinstance(response.content, str) else str(response.content)

            return self._parse_summary(content)

        except LLMServiceError:
            raise
        except Exception as e:
            raise LLMServiceError(f"Falha na sumarização: {str(e)}") from e

    def chat(self, question: str, context: str, history: list[dict]) -> str:
        """Responde pergunta sobre reunião mantendo contexto de conversa."""
        try:
            messages: list[BaseMessage] = [
                SystemMessage(content=CHAT_SYSTEM_PROMPT.format(transcript=context))
            ]
            for turn in history:
                if turn["role"] == "user":
                    messages.append(HumanMessage(content=turn["content"]))
                else:
                    messages.append(AIMessage(content=turn["content"]))
            messages.append(HumanMessage(content=question))

            response = self._llm.invoke(messages)
            content  = response.content if isinstance(response.content, str) else str(response.content)
            return content

        except LLMServiceError:
            raise
        except Exception as e:
            raise LLMServiceError(f"Falha no chat: {str(e)}") from e

    def _parse_summary(self, raw: str) -> Summary:
        """Parseia JSON da LLM removendo markdown fences se necessário."""
        try:
            cleaned = raw.strip()

            # Remove ```json ... ``` se o LLM incluir
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned.split("\n", 1)[1]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
            cleaned = cleaned.strip()

            data: dict = json.loads(cleaned)

            tasks = [
                Task(
                    description=t.get("description", ""),
                    responsible=t.get("responsible", "Não definido"),
                    deadline=t.get("deadline", "Não definido"),
                )
                for t in data.get("tasks", [])
            ]

            decisions = [
                Decision(
                    description=d.get("description", ""),
                    context=d.get("context", ""),
                )
                for d in data.get("decisions", [])
            ]

            return Summary(
                overview=data.get("overview", ""),
                topics=data.get("topics", []),
                tasks=tasks,
                decisions=decisions,
            )

        except (json.JSONDecodeError, KeyError) as e:
            raise LLMServiceError(
                f"JSON inválido da LLM: {str(e)}\nResposta: {raw[:300]}"
            ) from e