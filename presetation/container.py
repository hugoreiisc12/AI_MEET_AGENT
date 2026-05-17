"""
container.py — Injeção de dependência com suporte a dois modos.

SoloContainer  → uso individual: JSON local, sem fila, Streamlit direto.
CollabContainer → uso colaborativo: Postgres, Celery, FastAPI + Streamlit.

A factory get_container() decide qual usar via APP_MODE no .env.
"""

from functools import lru_cache
from config.settings import get_settings, AppMode

from infraestrutura.trasncriber.whisper_transcriber import WhisperTranscriber
from llm.langchain_llm_service import LangChainLLMService
from infraestrutura.json_meeting_repor import JsonMeetingRepository

from user_cases.transcribe_meeting import TranscribeMeetingUC
from user_cases.summarize_metting import SummarizeMeetingUC
from user_cases.chat_with_meeting import ChatWithMeetingUC


class SoloContainer:
    """
    Modo individual — tudo local, sem dependências externas.
    Funciona sem Docker, sem banco, sem Redis.
    """

    def __init__(self) -> None:
        settings = get_settings()

        # Infrastructure
        self._transcriber = WhisperTranscriber()
        self._llm = LangChainLLMService()
        self._repository = JsonMeetingRepository(
            storage_path=settings.storage_path
        )

        # Use cases
        self.transcribe_meeting = TranscribeMeetingUC(self._transcriber)
        self.summarize_meeting = SummarizeMeetingUC(self._llm, self._repository)
        self.chat_with_meeting = ChatWithMeetingUC(self._llm)
        self.repository = self._repository


class CollabContainer:
    """
    Modo colaborativo — requer Postgres e Celery.
    Requer: DATABASE_URL e REDIS_URL no .env.
    """

    def __init__(self) -> None:
        import warnings
        settings = get_settings()

        if not settings.database_url:
            raise RuntimeError(
                "APP_MODE=collab requer DATABASE_URL no .env.\n"
                "Exemplo: DATABASE_URL=postgresql+asyncpg://user:pass@localhost/meetagent"
            )

        # Infrastructure
        self._transcriber = WhisperTranscriber()
        self._llm = LangChainLLMService()

        # TODO: substituir por PostgresMeetingRepository quando implementado.
        # Atualmente usa JSON local mesmo em modo collab.
        warnings.warn(
            "CollabContainer está usando JsonMeetingRepository (armazenamento local). "
            "Implemente PostgresMeetingRepository e substitua aqui para produção.",
            stacklevel=2,
        )
        self._repository = JsonMeetingRepository(settings.storage_path)

        # Use cases — idênticos ao SoloContainer
        self.transcribe_meeting = TranscribeMeetingUC(self._transcriber)
        self.summarize_meeting = SummarizeMeetingUC(self._llm, self._repository)
        self.chat_with_meeting = ChatWithMeetingUC(self._llm)
        self.repository = self._repository


def build_container() -> SoloContainer | CollabContainer:
    """Factory — instancia o container correto baseado no APP_MODE."""
    settings = get_settings()
    if settings.app_mode == AppMode.COLLAB:
        return CollabContainer()
    return SoloContainer()


@lru_cache(maxsize=1)
def get_container() -> SoloContainer | CollabContainer:
    """Singleton por processo."""
    return build_container()