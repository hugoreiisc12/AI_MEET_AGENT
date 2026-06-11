"""
container.py — Injeção de dependência com suporte a dois modos.

SoloContainer  → uso individual: JSON local, sem fila, Streamlit direto.
CollabContainer → uso colaborativo: Postgres, Celery, FastAPI + Streamlit.

A factory get_container() decide qual usar via APP_MODE no .env.
"""

from functools import lru_cache
from typing import Optional, Any
from config.settings import get_settings, AppMode

from infrastructure.llm.langchain_llm_service import LangChainLLMService
from infrastructure.json_meeting_repository import JsonMeetingRepository

from use_cases.record_meeting import RecordMeetingUC
from use_cases.transcribe_meeting import TranscribeMeetingUC
from use_cases.summarize_meeting import SummarizeMeetingUC
from use_cases.chat_with_meeting import ChatWithMeetingUC
from use_cases.analyze_sentiment import AnalyzeSentimentUC
from use_cases.fetch_meeting_context import FetchMeetingContextUC


def _build_transcriber(settings):
    use_local = settings.use_local_whisper

    if use_local:
        from infrastructure.transcriber.whisper_local_transcriber import WhisperLocalTranscriber
        return WhisperLocalTranscriber()

    if settings.use_real_diarization:
        from infrastructure.transcriber.whisper_with_diarization import WhisperWithDiarization
        return WhisperWithDiarization()

    from infrastructure.transcriber.whisper_transcriber import WhisperTranscriber
    return WhisperTranscriber()


def _build_common(settings, repository) -> dict:
    transcriber = _build_transcriber(settings)
    llm         = LangChainLLMService()

    transcribe_meeting = TranscribeMeetingUC(transcriber)
    summarize_meeting  = SummarizeMeetingUC(llm, repository)
    chat_with_meeting  = ChatWithMeetingUC(llm)

    from infrastructure.llm.sentiment_analyzer import SentimentAnalyzer
    sentiment_analyzer = SentimentAnalyzer(llm_client=llm._llm)
    analyze_sentiment  = AnalyzeSentimentUC(analyzer=sentiment_analyzer)

    fetch_meeting_context = None
    if getattr(settings, "enable_calendar", False):
        from infrastructure.calendar.google_calendar_service import GoogleCalendarService
        calendar = GoogleCalendarService(
            credentials_path=getattr(settings, "google_credentials_path", "credentials.json"),
            token_path=getattr(settings, "google_token_path", "token.json"),
        )
        fetch_meeting_context = FetchMeetingContextUC(calendar)

    record_meeting = None
    recorder_provider = getattr(settings, "recorder_provider", "none")

    if recorder_provider == "playwright":
        from infrastructure.recorder.playwright_bot_recorder import PlaywrightBotRecorder

        recorder = PlaywrightBotRecorder(
            chrome_profile_dir=getattr(settings, "bot_chrome_profile", "./bot_chrome_profile"),
            audio_dir=settings.audio_storage_path,
            bot_name=getattr(settings, "bot_name", "Meet Agent"),
            headless=getattr(settings, "bot_headless", False),
            on_audio_ready=_make_delivery_callback(settings),
        )
        record_meeting = RecordMeetingUC(recorder=recorder)

    from agents.etl_agent import ETLAgent
    from agents.collection_agent import CollectionAgent
    from agents.orchestrator_agent import OrchestratorAgent
    from agents.memory_manager import MemoryManager

    etl_agent = ETLAgent(
        transcribe_uc=transcribe_meeting,
        llm=llm,
        repository=repository,
    )

    memory_manager = MemoryManager(
        repository=repository,
        short_term_max=5,
        medium_term_threshold=3,
        long_term_threshold=10,
    )

    collection_agent = CollectionAgent(
        repository=repository,
        memory_manager=memory_manager,
    )

    orchestrator = OrchestratorAgent(
        recorder=recorder if record_meeting else None,
        etl_agent=etl_agent,
        collection_agent=collection_agent,
        repository=repository,
    ) if record_meeting else None

    return {
        "_transcriber":          transcriber,
        "_llm":                  llm,
        "_repository":           repository,
        "transcribe_meeting":    transcribe_meeting,
        "summarize_meeting":     summarize_meeting,
        "chat_with_meeting":     chat_with_meeting,
        "analyze_sentiment":     analyze_sentiment,
        "fetch_meeting_context": fetch_meeting_context,
        "record_meeting":        record_meeting,
        "repository":            repository,
        "etl_agent":             etl_agent,
        "collection_agent":      collection_agent,
        "memory_manager":        memory_manager,
        "orchestrator":          orchestrator,
    }


def _make_delivery_callback(settings):
    if getattr(settings, "app_mode", "solo") != "collab":
        return None

    async def deliver(audio_path, speaker_log_path):
        from worker.tasks import process_meeting_task
        meeting_id = audio_path.stem
        process_meeting_task.delay(
            meeting_id=meeting_id,
            audio_path=audio_path.as_posix(),
            title="",
        )

    return deliver


class SoloContainer:
    repository: JsonMeetingRepository
    record_meeting: Any | None
    transcribe_meeting: TranscribeMeetingUC
    summarize_meeting: SummarizeMeetingUC
    chat_with_meeting: ChatWithMeetingUC
    analyze_sentiment: AnalyzeSentimentUC
    fetch_meeting_context: FetchMeetingContextUC | None

    def __init__(self) -> None:
        settings   = get_settings()
        repository = JsonMeetingRepository(storage_path=settings.storage_path)
        self.__dict__.update(_build_common(settings, repository))


class CollabContainer:
    repository: JsonMeetingRepository
    record_meeting: Any | None
    transcribe_meeting: TranscribeMeetingUC
    summarize_meeting: SummarizeMeetingUC
    chat_with_meeting: ChatWithMeetingUC
    analyze_sentiment: AnalyzeSentimentUC
    fetch_meeting_context: FetchMeetingContextUC | None

    def __init__(self) -> None:
        import warnings
        settings = get_settings()

        if not settings.mongo_uri:
            raise RuntimeError(
                "APP_MODE=collab requer MONGO_URI no .env.\n"
                "Exemplo: MONGO_URI=mongodb://mongo:27017/meetagent"
            )

        from infrastructure.storage_mongodb import MongoDBMeetingRepository
        repository = MongoDBMeetingRepository(
            mongo_uri=settings.mongo_uri,
            db_name=settings.mongo_db,
        )
        self.__dict__.update(_build_common(settings, repository))

        try:
            from worker.tasks import start_background_worker
            start_background_worker()
        except Exception as e:
            warnings.warn(f"Não foi possível iniciar worker background: {e}", stacklevel=2)


def build_container() -> SoloContainer | CollabContainer:
    settings = get_settings()
    if settings.app_mode == AppMode.COLLAB:
        return CollabContainer()
    return SoloContainer()


@lru_cache(maxsize=1)
def get_container() -> SoloContainer | CollabContainer:
    return build_container()
