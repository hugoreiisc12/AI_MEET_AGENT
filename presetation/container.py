# Container para injeção de depedência manual, que monta a árvore de objetos e fornece os use cases prontos para a presentation layer.
from functools import lru_cache

from infraestrutura.transcriber.whisper_transcriber import WhisperTranscriber
from infraestrutura.llm.langchain_llm_service import LangChainLLMService
from infraestrutura.storage.json_meeting_repository import JsonMeetingRepository

from use_cases.transcribe_meeting import TranscribeMeetingUC
from use_cases.summarize_meeting import SummarizeMeetingUC
from use_cases.chat_with_meeting import ChatWithMeetingUC

"""
Container.py — Injeção de Dependência manual.

Monta uma árvore de objetos uma única vez e fornece
os use cases prontos para a presentation layer.

Por que não usar um framework de DI?
  - Fácil de substituir por dependency-injector ou similar no futuro.
"""

# Defindo classe para container de injeção de dependência manual, que monta a árvore de objetos e fornece os use cases prontos para a presentation layer.
class Container:
    """Registra e fornece todas as dependências do projeto."""

    def __init__(self) -> None:
        # Infraestrutura (concreto)
        self._transcriber = WhisperTranscriber()
        self._llm_service = LangChainLLMService()
        self._repository = JsonMeetingRepository()

        # Use cases (injeção)
        self.transcribe_meeting = TranscribeMeetingUC(
            transcriber=self._transcriber,
        )
        self.summarize_meeting = SummarizeMeetingUC(
            llm_service=self._llm_service,
            repository=self._repository,
        )
        self.chat_with_meeting = ChatWithMeetingUC(
            llm_service=self._llm_service,
        )
        self.repository = self._repository


# Função para obter o container, decorada com lru_cache para garantir que seja um singleton, ou seja, criado apenas uma vez por processo.
@lru_cache(maxsize=1)
def get_container() -> Container:
    """Singleton — o container é criado uma única vez por processo."""
    return Container()