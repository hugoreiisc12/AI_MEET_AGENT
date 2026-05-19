# Interface de serviço de LLM que define o contrato para qualquer implementação
from abc import ABC, abstractmethod 
from entities.meeting import Summary
# Classe abstrata que qualquer serviço de LLM deve implementar
class ILLMService(ABC):
    """Contrato para qualquer implementação de serviço de LLM."""

    # Método para resumir transcrição em Summary estruturado
    @abstractmethod
    def summarize(self, transcript: str) -> Summary:
        """Resumo estruturado com tópicos, tarefas, decisões e visão geral."""

    # Método para responder perguntas sobre a reunião
    @abstractmethod
    def chat(self, question: str, context: str, history: list[dict]) -> str:
        """Responde pergunta sobre reunião com contexto e histórico."""


# Exceção específica para erros durante chamadas ao LLM
class LLMServiceError(Exception):
    """Erro durante chamada a LLM."""
    pass