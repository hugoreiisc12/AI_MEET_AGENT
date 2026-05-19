# Implementação de LLM service usando LangChain + OpenAI para processamento de reuniões
import json
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, BaseMessage
from pydantic import SecretStr

from entities.meeting import Summary, Task, Decision
from interface.llm_services import ILLMService, LLMServiceError
from config.settings import get_settings

# Prompt para sumarização: instrui LLM a retornar JSON estruturado
SUMMARIZE_SYSTEM_PROMPT = """Você é um assistente de IA especializado em resumir reuniões corporativas.

Analise a transcrição fornecida e retorne um JSON com exatamente esta estrutura:

{
   "overview": "Parágrafo de 2-3 linhas resumindo o propósito e resultado da reunião",
   "topics": ["Tópico 1", "Tópico 2"],
   "tasks": [
    {
        "description": "Descrição com detalhes da tarefa",
        "responsible": "Nome ou 'Não definido'",
        "deadline": "Prazo mencionado ou 'Não definido'"
    }
   ],
   "decisions": [
    {
      "description": "Descrição da tomada de decisão",
      "context": "Contexto do que e porque foi definido"
    }
   ]
}

Regras:
- Responda APENAS com um JSON, sem texto antes ou depois
- Se um campo não for identificado, use lista vazia [] ou string vazia ""
- Extraia apenas o que está explicitamente na transcrição
- Escreva em português Brasil
"""

# Prompt para chat: instrui LLM a responder perguntas sobre reunião
CHAT_SYSTEM_PROMPT = """Você é um assistente de reuniões. Você participou da reunião abaixo e pode responder perguntas sobre ela.

TRANSCRIÇÃO DA REUNIÃO:
{transcript}

Regras:
- Responda sempre em português Brasil
- Se a informação não tiver na transcrição, responda "Isso não foi mencionado na reunião"
- Seja direto e objetivo
- Cite a fonte quando possível (ex: "Conforme mencionado por Speaker 0...")"""


# Implementação de ILLMService usando LangChain + GPT-4o
class LangChainLLMService(ILLMService):
    """Serviço de LLM com LangChain orquestrando chamadas OpenAI."""

    # Construtor que recebe LLM ou cria um novo com configurações
    def __init__(self, llm: ChatOpenAI | None = None) -> None:
        settings = get_settings()
        self._llm = llm or ChatOpenAI(
            model=settings.openai_model,
            api_key=SecretStr(settings.openai_api_key),
            temperature=0.2,  # Baixo para respostas consistentes
        )
        self._current_transcript: str = ""

    # Sumariza transcrição em Summary estruturado
    def summarize(self, transcript: str) -> Summary:
        """Analisa transcrição e retorna Summary com tópicos, tarefas, decisões."""
        try:
            messages: list[BaseMessage] = [
                SystemMessage(content=SUMMARIZE_SYSTEM_PROMPT),
                HumanMessage(content=f"Transcrição:\n{transcript}"),
            ]
            response = self._llm.invoke(messages)
            content = response.content if isinstance(response.content, str) else str(response.content)
            return self._parse_summary(content)
        except Exception as e:
            raise LLMServiceError(f"Falha na sumarização: {str(e)}") from e

    # Responde pergunta sobre reunião com histórico
    def chat(self, question: str, context: str, history: list[dict]) -> str:
        """Responde pergunta sobre reunião mantendo contexto de conversa."""
        try:
            # Monta mensagens: system com transcrição + histórico + pergunta
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
            content = response.content if isinstance(response.content, str) else str(response.content)
            return content

        except Exception as e:
            raise LLMServiceError(f"Falha no chat: {str(e)}") from e

    # Converte JSON retornado pelo LLM em entidade Summary
    def _parse_summary(self, raw: str) -> Summary:
        """Parseia JSON da LLM removendo markdown fences se necessário."""
        try:
            cleaned = raw.strip()
            # Remove ```json ... ``` se o LLM as incluir
            if cleaned.startswith("```json"):
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