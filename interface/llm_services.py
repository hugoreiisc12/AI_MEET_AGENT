from abc import ABC, abstractmethod
from domain.entities.meeting import Summary
from domain.entities.meeting_type import MeetingType


class ILLMService(ABC):
    """Contrato para qualquer implementação de serviço de LLM."""

    @abstractmethod
    def summarize(self, transcript: str, meeting_type: MeetingType = MeetingType.GENERAL) -> Summary:
        """Resumo estruturado com tópicos, tarefas, decisões e visão geral."""

    @abstractmethod
    def chat(self, question: str, context: str, history: list[dict], summary_context: str = "", user_id: str | None = None) -> str:
        """Responde pergunta sobre reunião com contexto, histórico, sumário e identificação do usuário."""


class LLMServiceError(Exception):
    """Erro durante chamada a LLM."""
    pass