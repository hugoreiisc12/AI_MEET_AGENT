from abc import ABC, abstractmethod
from domain.entities.meeting import Summary
from domain.entities.meeting_type import MeetingType


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
    def chat(self, question: str, context: str, history: list[dict], summary_context: str = "", user_id: str | None = None) -> str:
        """Responde pergunta sobre reunião com contexto, histórico, sumário e identificação do usuário.

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