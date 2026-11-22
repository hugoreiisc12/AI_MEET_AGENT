from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from domain.entities.meeting import Summary
from domain.entities.meeting_type import MeetingType


@dataclass
class ChatReply:
    """Resposta do chat. `tool` = ferramenta que o agente pediu para usar, no lugar de responder:
    {"name": "send_email" | "create_document", "arguments": {...}}. Quem executa é o caso de uso."""
    answer: str
    tool: Optional[dict] = None


class ILLMService(ABC):
    """Contrato para qualquer implementação de serviço de LLM.

    Regras contratuais obrigatórias:
    1. Resposta SEMPRE em português do Brasil
    2. Fidelidade absoluta ao que foi dito na reunião — nunca inventar informações
    3. Quando não souber a resposta, dizer educadamente que o assunto não foi
       mencionado na reunião, em vez de inventar
    4. Respostas completas e contextuais, nunca secas ou muito diretas —
       fornecer informações detalhadas e verdadeiras sempre que possível
    5. Honestidade: deixar claro quando está interpretando vs. citando a transcrição
    """

    @abstractmethod
    def summarize(self, transcript: str, meeting_type: MeetingType = MeetingType.GENERAL) -> Summary:
        """Resumo estruturado com tópicos, tarefas, decisões e visão geral.
        Deve ser fiel à transcrição, sem inventar informações.
        """

    @abstractmethod
    def chat(self, question: str, context: str, history: list[dict], summary_context: str = "",
             user_id: str | None = None, question_context: str = "", can_search: bool = False,
             on_delta=None) -> str:
        """Responde pergunta sobre reunião com contexto, histórico, sumário e identificação do usuário.
        `context` é o que vale para a conversa toda (a reunião aberta); `question_context`, o que foi
        buscado para esta pergunta (trechos, outras reuniões) e vai junto com ela.

        Contrato de resposta:
        - Português do Brasil obrigatório
        - Fiel ao que foi dito na reunião
        - Dizer "não foi mencionado" quando não souber
        - Respostas completas e contextuais, nunca secas
        - Informações verdadeiras baseadas exclusivamente na transcrição
        """


class LLMServiceError(Exception):
    """Erro durante chamada a LLM."""
    pass