"""
container.py — Injeção de dependência com suporte a dois modos.

SoloContainer  → uso individual: JSON local, sem fila, Streamlit direto.
CollabContainer → uso colaborativo: Postgres, Celery, FastAPI + Streamlit.

A factory get_container() decide qual usar via APP_MODE no .env.
"""

from functools import lru_cache
from config.settings import get_settings, AppMode

from infrastructure.transcriber.whisper_transcriber import WhisperTranscriber
from llm.langchain_llm_service import LangChainLLMService
from infrastructure.json_meeting_repor import JsonMeetingRepository

from use_cases.transcribe_meeting import TranscribeMeetingUC
from use_cases.analyze_sentiment import AnalyzeSentimentUC
from use_cases.fetch_meeting_context import FetchMeetingContextUC
from use_cases.summarize_meeting import SummarizeMeetingUC
from use_cases.chat_with_meeting import ChatWithMeetingUC


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

        # Use cases Fase 6
        from infrastructure.llm.sentiment_analyzer import SentimentAnalyzer
        self._sentiment_analyzer = SentimentAnalyzer(llm_client=self._llm._llm)
        self.analyze_sentiment = AnalyzeSentimentUC(analyzer=self._sentiment_analyzer)

        if settings.enable_calendar:
            from infrastructure.calendar.google_calendar_service import GoogleCalendarService
            self._calendar = GoogleCalendarService(
                credentials_path=settings.google_credentials_path,
                token_path=settings.google_token_path,
            )
            self.fetch_meeting_context = FetchMeetingContextUC(self._calendar)
        else:
            self.fetch_meeting_context = None


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

        # Use cases Fase 6
        from infrastructure.llm.sentiment_analyzer import SentimentAnalyzer
        self._sentiment_analyzer = SentimentAnalyzer(llm_client=self._llm._llm)
        self.analyze_sentiment = AnalyzeSentimentUC(analyzer=self._sentiment_analyzer)

        if settings.enable_calendar:
            from infrastructure.calendar.google_calendar_service import GoogleCalendarService
            self._calendar = GoogleCalendarService(
                credentials_path=settings.google_credentials_path,
                token_path=settings.google_token_path,
            )
            self.fetch_meeting_context = FetchMeetingContextUC(self._calendar)
        else:
            self.fetch_meeting_context = None


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