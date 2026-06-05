# Implementação de LLM service usando LangChain para processamento de reuniões
# Suporta OpenAI, Ollama (local) e OpenRouter
import json
import re
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

Regras:
- Responda sempre em português Brasil
- Se a informação não estiver na transcrição, responda "Isso não foi mencionado na reunião"
- Não invente falas, participantes ou horários
- Seja direto e objetivo
- Cite a fonte quando possível (ex: "Conforme mencionado por Speaker 0...")"""


class LangChainLLMService(ILLMService):
    """Serviço de LLM com LangChain — suporta OpenAI, Ollama e OpenRouter."""

    def __init__(self, llm: ChatOpenAI | None = None) -> None:
        settings = get_settings()
        self._prompt_builder = PromptBuilder()
        self._current_transcript: str = ""

        if llm:
            # Injeção direta — usado em testes
            self._llm = llm

        elif getattr(settings, "llm_provider", "openai") == "ollama":
            # LLM local via Ollama — sem custo, sem internet
            self._llm = ChatOpenAI(
                model=getattr(settings, "ollama_model", "nemotron-mini"),
                api_key=SecretStr("ollama"),  # Ollama não valida a key
                base_url=getattr(settings, "ollama_base_url", "http://localhost:11434/v1"),
                temperature=settings.llm_temperature,
                top_p=settings.llm_top_p,
            )

        elif getattr(settings, "llm_provider", "openai") == "openrouter":
            # OpenRouter — acesso a múltiplos modelos com uma chave
            self._llm = ChatOpenAI(
                model=getattr(settings, "openrouter_model", "openai/gpt-4o"),
                api_key=SecretStr(getattr(settings, "openrouter_api_key", "")),
                base_url="https://openrouter.ai/api/v1",
                temperature=settings.llm_temperature,
                top_p=settings.llm_top_p,
                default_headers={
                    "HTTP-Referer": getattr(settings, "openrouter_site_url", ""),
                    "X-Title": getattr(settings, "openrouter_site_name", "Meet Agent"),
                },
            )

        else:
            # OpenAI direto — padrão
            self._llm = ChatOpenAI(
                model=settings.openai_model,
                api_key=SecretStr(settings.openai_api_key),
                temperature=settings.llm_temperature,
                top_p=settings.llm_top_p,
            )

    def summarize(self, transcript: str, meeting_type: MeetingType = MeetingType.GENERAL) -> Summary:
        """Analisa transcrição e retorna Summary com tópicos, tarefas, decisões."""
        try:
            system_prompt = self._prompt_builder.build_summarize_system(meeting_type)
            user_message  = self._prompt_builder.build_summarize_user(transcript)

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
        cleaned = self._extract_json(raw)

        try:
            data: dict = json.loads(cleaned)
        except (json.JSONDecodeError, KeyError) as e:
            recovered = self._recover_invalid_json(cleaned)
            try:
                data = json.loads(recovered)
            except Exception:
                raise LLMServiceError(
                    f"JSON inválido da LLM: {str(e)}\nResposta: {raw[:300]}"
                ) from e

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

    def _extract_json(self, raw: str) -> str:
        cleaned = raw.strip()

        if cleaned.startswith("```"):
            parts = cleaned.split("```")
            if len(parts) >= 3:
                if parts[1].strip().lower().startswith("json"):
                    cleaned = parts[2]
                else:
                    cleaned = parts[1]
            else:
                cleaned = cleaned.replace("```", "")

        if cleaned.lower().startswith("json"):
            cleaned = cleaned.split("\n", 1)[-1]

        cleaned = cleaned.strip()

        first_brace = cleaned.find("{")
        if first_brace != -1:
            cleaned = cleaned[first_brace:]

        return cleaned.strip()

    def _recover_invalid_json(self, raw: str) -> str:
        candidate = raw.strip()
        candidate = re.sub(r",\s*([}\]])", r"\1", candidate)

        brace_balance = 0
        bracket_balance = 0
        for ch in candidate:
            if ch == "{":
                brace_balance += 1
            elif ch == "}":
                brace_balance -= 1
            elif ch == "[":
                bracket_balance += 1
            elif ch == "]":
                bracket_balance -= 1

        if brace_balance > 0:
            candidate += "}" * brace_balance
        if bracket_balance > 0:
            candidate += "]" * bracket_balance

        return candidate