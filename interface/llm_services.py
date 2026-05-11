# Interface de serviço de LLM que define o contrato para qualquer implementação

from abc import ABC, abstractmethod
from entities.transcript import Transcript, Segment  # CORRIGIDO: domain.entises → entities
from entities.metting import Summary  # CORRIGIDO: Summarize → Summary


# Definindo a classe abstrata que qualquer serviço de LLM deve implementar
class ILLMService(ABC):
    """
    Contrato de qualquer serviço de LLM.
    O domain não sabe se é GPT-4o, Claude ou outro.
    """

    @abstractmethod
    def summarize(self, transcript: str) -> Summary:  # CORRIGIDO: Summarize → Summary
        """
        Recebe a transcrição em texto, e devolve Summary estruturado.

        Args:
            transcript: Texto completo ou formatado de reunião

        Returns:
            Summary com topics, tasks, decisions e overview

        Raises:
            LLMServiceError: se a chamada a LLM falhar
        """

    @abstractmethod
    def chat(self, question: str, context: str, history: list[dict]) -> str:
        """
        Responde uma pergunta sobre a reunião com base na transcrição.

        Args:
            question: Pergunta do usuário sobre a reunião
            context: Transcrição ou resumo da reunião para fornecer contexto
            history: Lista de dicts [{"role": "user" ou "assistant", "content": str}]

        Returns:
            Resposta em texto da LLM
        """


# Definindo classe de erro específica para falhas no processo de chamada a LLM
class LLMServiceError(Exception):
    """Erro durante chamada a LLM."""
    pass