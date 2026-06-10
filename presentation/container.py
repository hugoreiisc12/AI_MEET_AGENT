"""
container.py — Injeção de dependência com suporte a dois modos.

SoloContainer  → uso individual: JSON local, sem fila, Streamlit direto.
CollabContainer → uso colaborativo: Postgres, Celery, FastAPI + Streamlit.

A factory get_container() decide qual usar via APP_MODE no .env.
"""

from functools import lru_cache
from typing import Optional, Any
from config.settings import get_settings, AppMode

from domain.entities.calendar_event import CalendarEvent
from infrastructure.llm.langchain_llm_service import LangChainLLMService
from infrastructure.agents.etl_flow_agent import ETLFlowAgent
from infrastructure.agents.validation_query_agent import ValidationQueryAgent
from infrastructure.agents.pipeline_orchestrator_agent import PipelineOrchestratorAgent
from infrastructure.json_meeting_repository import JsonMeetingRepository
from infrastructure.sqlite_meeting_repository import SqliteMeetingRepository
from infrastructure.mongo_setup import init_mongo

from use_cases.record_meeting import RecordMeetingUC
from use_cases.transcribe_meeting import TranscribeMeetingUC
from use_cases.summarize_meeting import SummarizeMeetingUC
from use_cases.chat_with_meeting import ChatWithMeetingUC
from use_cases.analyze_sentiment import AnalyzeSentimentUC
from use_cases.fetch_meeting_context import FetchMeetingContextUC


def _build_transcriber(settings):
    """Instancia o transcriber local (WhisperLocalTranscriber)."""
    from infrastructure.transcriber.whisper_local_transcriber import WhisperLocalTranscriber
    return WhisperLocalTranscriber()


def _build_pipeline_orchestrator(repository, transcribe_uc, summarize_uc, chat_uc=None):
    from infrastructure.transcriber.block_based_transcriber import BlockBasedTranscriber
    from infrastructure.pipeline.meeting_pipeline_orchestrator import MeetingPipelineOrchestrator

    return MeetingPipelineOrchestrator(
        repository=repository,
        transcribe_uc=transcribe_uc,
        summarize_uc=summarize_uc,
        block_transcriber=BlockBasedTranscriber(),
        chat_uc=chat_uc,
    )


def _build_common(settings, repository) -> dict:
    """
    Monta os componentes compartilhados entre Solo e Collab.
    Elimina duplicação — qualquer mudança feita aqui vale para os dois modos.
    """
    transcriber = _build_transcriber(settings)
    llm         = LangChainLLMService()

    transcribe_meeting = TranscribeMeetingUC(transcriber)
    summarize_meeting  = SummarizeMeetingUC(llm, repository)
    chat_with_meeting  = ChatWithMeetingUC(llm)

    # Orquestrador do pipeline: transcreve → sumariza em cadeia
    pipeline_orchestrator = _build_pipeline_orchestrator(
        repository, transcribe_meeting, summarize_meeting, chat_with_meeting,
    )

    from infrastructure.llm.sentiment_analyzer import SentimentAnalyzer
    sentiment_analyzer = SentimentAnalyzer(llm_client=llm._llm)
    analyze_sentiment  = AnalyzeSentimentUC(analyzer=sentiment_analyzer)

    fetch_meeting_context = None
    calendar_event: CalendarEvent | None = None
    if getattr(settings, "enable_calendar", False):
        from infrastructure.calendar.google_calendar_service import GoogleCalendarService
        from use_cases.fetch_meeting_context import FetchMeetingContextInput

        calendar = GoogleCalendarService(
            credentials_path=getattr(settings, "google_credentials_path", "credentials.json"),
            token_path=getattr(settings, "google_token_path", "token.json"),
        )
        fetch_meeting_context = FetchMeetingContextUC(calendar)

        try:
            context_output = fetch_meeting_context.execute(
                FetchMeetingContextInput(use_current=True)
            )
            if context_output.success:
                calendar_event = context_output.event
        except Exception:
            calendar_event = None

    record_meeting = None
    recorder_provider = getattr(settings, "recorder_provider", "none")

    if recorder_provider == "playwright":
        email    = getattr(settings, "bot_google_email", "")
        password = getattr(settings, "bot_google_password", "")

        if not email or not password:
            import warnings
            warnings.warn(
                "BOT_GOOGLE_EMAIL e BOT_GOOGLE_PASSWORD não configurados. "
                "Bot de reunião desativado. Execute: python bot_setup.py",
                stacklevel=2,
            )
        else:
            from infrastructure.recorder.playwright_bot_recorder import PlaywrightBotRecorder

            recorder = PlaywrightBotRecorder(
                chrome_profile_dir=getattr(settings, "bot_chrome_profile", "./bot_chrome_profile"),
                audio_dir=settings.audio_storage_path,
                bot_name=getattr(settings, "bot_name", "Meet Agent"),
                headless=getattr(settings, "bot_headless", False),
            )
            record_meeting = RecordMeetingUC(recorder=recorder)

    etl_agent = ETLFlowAgent(
        transcriber=transcriber,
        repository=repository,
    )
    validation_agent = ValidationQueryAgent(repository=repository)
    pipeline_agent = PipelineOrchestratorAgent(
        repository=repository,
        transcribe_uc=transcribe_meeting,
        summarize_uc=summarize_meeting,
        chat_uc=chat_with_meeting,
        etl_agent=etl_agent,
        validation_agent=validation_agent,
    )

    return {
        "_transcriber":           transcriber,
        "_llm":                   llm,
        "_repository":            repository,
        "transcribe_meeting":     transcribe_meeting,
        "summarize_meeting":      summarize_meeting,
        "chat_with_meeting":      chat_with_meeting,
        "analyze_sentiment":      analyze_sentiment,
        "fetch_meeting_context":  fetch_meeting_context,
        "calendar_event":         calendar_event,
        "record_meeting":         record_meeting,
        "repository":             repository,
        "pipeline_orchestrator":  pipeline_orchestrator,
        "etl_agent":              etl_agent,
        "validation_agent":       validation_agent,
        "pipeline_agent":         pipeline_agent,
    }


class SoloContainer:
    repository: JsonMeetingRepository
    record_meeting: Any | None
    transcribe_meeting: TranscribeMeetingUC
    summarize_meeting: SummarizeMeetingUC
    chat_with_meeting: ChatWithMeetingUC
    analyze_sentiment: AnalyzeSentimentUC
    fetch_meeting_context: FetchMeetingContextUC | None
    calendar_event: CalendarEvent | None

    def __init__(self) -> None:
        settings   = get_settings()
        repository = JsonMeetingRepository(storage_path=settings.storage_path)
        self.__dict__.update(_build_common(settings, repository))


class CollabContainer:
    repository: SqliteMeetingRepository
    record_meeting: Any | None
    transcribe_meeting: TranscribeMeetingUC
    summarize_meeting: SummarizeMeetingUC
    chat_with_meeting: ChatWithMeetingUC
    analyze_sentiment: AnalyzeSentimentUC
    fetch_meeting_context: FetchMeetingContextUC | None
    calendar_event: CalendarEvent | None

    def __init__(self) -> None:
        settings = get_settings()

        repository_path = settings.repository_path
        if settings.database_url:
            if settings.database_url.startswith("sqlite"):
                repository_path = settings.database_url
            else:
                raise RuntimeError(
                    "APP_MODE=collab suporta apenas SQLite local no momento. "
                    "Use REPOSITORY_PATH=./data/meetings.db ou DATABASE_URL=sqlite:///data/meetings.db"
                )

        repository = SqliteMeetingRepository(repository_path)
        self.__dict__.update(_build_common(settings, repository))


class MongoContainer:
    repository: "MongoMeetingRepository"  # noqa: F821
    record_meeting: Any | None
    transcribe_meeting: TranscribeMeetingUC
    summarize_meeting: SummarizeMeetingUC
    chat_with_meeting: ChatWithMeetingUC
    analyze_sentiment: AnalyzeSentimentUC
    fetch_meeting_context: FetchMeetingContextUC | None
    calendar_event: CalendarEvent | None

    def __init__(self) -> None:
        from infrastructure.mongo_meeting_repository import MongoMeetingRepository

        settings = get_settings()
        init_mongo(settings.mongo_uri, settings.mongo_db_name)
        repository = MongoMeetingRepository()
        self.__dict__.update(_build_common(settings, repository))


import logging as _logging

_container_logger = _logging.getLogger(__name__)

_mongo_fallback_warning: str | None = None


def get_mongo_fallback_warning() -> str | None:
    """Retorna aviso de fallback do MongoDB, se houver."""
    return _mongo_fallback_warning


def build_container() -> SoloContainer | CollabContainer | MongoContainer:
    """Factory sem cache — use em testes para obter container sempre fresco."""
    global _mongo_fallback_warning
    settings = get_settings()
    if settings.use_mongo:
        try:
            return MongoContainer()
        except Exception as e:
            _mongo_fallback_warning = (
                f"MongoDB indisponível ({e}). "
                "Usando repositório local. Verifique se o serviço está ativo."
            )
            _container_logger.warning(_mongo_fallback_warning)
    if settings.app_mode == AppMode.COLLAB:
        return CollabContainer()
    return SoloContainer()


@lru_cache(maxsize=1)
def get_container() -> SoloContainer | CollabContainer | MongoContainer:
    """Singleton por processo.

    ATENÇÃO: se fizer get_settings.cache_clear() em testes,
    chame também get_container.cache_clear().
    Em testes prefira build_container() diretamente.
    """
    return build_container()