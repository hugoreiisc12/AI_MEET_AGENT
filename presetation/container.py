"""
container.py — Injeção de dependência com suporte a dois modos.

SoloContainer  → uso individual: JSON local, sem fila, Streamlit direto.
CollabContainer → uso colaborativo: Postgres, Celery, FastAPI + Streamlit.

A factory get_container() decide qual usar via APP_MODE no .env.
"""

from functools import lru_cache
from config.settings import get_settings, AppMode

from infrastructure.transcriber.whisper_transcriber import WhisperTranscriber
from infrastructure.llm.langchain_llm_service import LangChainLLMService
from infrastructure.storage.json_meeting_repository import JsonMeetingRepository

from use_cases.transcribe_meeting import TranscribeMeetingUC
from use_cases.summarize_meeting import SummarizeMeetingUC
from use_cases.chat_with_meeting import ChatWithMeetingUC
from use_cases.record_meeting import RecordMeetingUC


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

        # Recorder — importado só se pyaudio disponível
        try:
            from infrastructure.recorder.pyaudio_recorder import PyAudioRecorder
            self._recorder = PyAudioRecorder()
            self.record_meeting = RecordMeetingUC(self._recorder)
        except ImportError:
            self._recorder = None
            self.record_meeting = None


class CollabContainer:
    """
    Modo colaborativo — Postgres, Celery, FastAPI.
    Requer: DATABASE_URL e REDIS_URL no .env.
    """

    def __init__(self) -> None:
        settings = get_settings()

        if not settings.database_url:
            raise RuntimeError(
                "APP_MODE=collab requer DATABASE_URL no .env.\n"
                "Exemplo: DATABASE_URL=postgresql+asyncpg://user:pass@localhost/meetagent"
            )

        # Infrastructure
        self._transcriber = WhisperTranscriber()
        self._llm = LangChainLLMService()

        from infrastructure.storage.postgres_meeting_repository import PostgresMeetingRepository
        self._repository = PostgresMeetingRepository(settings.database_url)

        # Use cases — idênticos ao SoloContainer
        self.transcribe_meeting = TranscribeMeetingUC(self._transcriber)
        self.summarize_meeting = SummarizeMeetingUC(self._llm, self._repository)
        self.chat_with_meeting = ChatWithMeetingUC(self._llm)
        self.repository = self._repository
        self.record_meeting = None  # gravação via extensão Chrome no modo collab


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