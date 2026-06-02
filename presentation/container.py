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
    """
    Instancia o transcriber correto baseado nas settings.

    Decisão em duas etapas:
      1. API ou local? → WHISPER_TRANSCRIBER=api|local
      2. Se local, com diarização real? → USE_REAL_DIARIZATION=true|false

    Combinações:
      WHISPER_TRANSCRIBER=api  + USE_REAL_DIARIZATION=false → WhisperTranscriber (API OpenAI)
      WHISPER_TRANSCRIBER=api  + USE_REAL_DIARIZATION=true  → WhisperWithDiarization (API + pyannote)
      WHISPER_TRANSCRIBER=local + USE_REAL_DIARIZATION=false → WhisperLocalTranscriber
      WHISPER_TRANSCRIBER=local + USE_REAL_DIARIZATION=true  → WhisperLocalTranscriber + pyannote (futuro)
    """
    use_local = settings.use_local_whisper

    if use_local:
        from infrastructure.transcriber.whisper_local_transcriber import WhisperLocalTranscriber
        return WhisperLocalTranscriber()

    # API OpenAI
    if settings.use_real_diarization:
        from infrastructure.transcriber.whisper_with_diarization import WhisperWithDiarization
        return WhisperWithDiarization()

    from infrastructure.transcriber.whisper_transcriber import WhisperLocalTranscriber
    return WhisperLocalTranscriber()


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
                google_email=email,
                google_password=password,
                profile_dir=getattr(settings, "bot_chrome_profile", "./bot_chrome_profile"),
                bot_name=getattr(settings, "bot_name", "Meet Agent 🤖"),
                output_dir=settings.audio_storage_path,
                headless=getattr(settings, "bot_headless", False),
            )
            record_meeting = RecordMeetingUC(recorder=recorder)

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
    }


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

        if not settings.database_url:
            raise RuntimeError(
                "APP_MODE=collab requer DATABASE_URL no .env.\n"
                "Exemplo: DATABASE_URL=postgresql+asyncpg://user:pass@localhost/meetagent"
            )

        warnings.warn(
            "CollabContainer usando JsonMeetingRepository (storage local). "
            "Implemente PostgresMeetingRepository para produção real.",
            stacklevel=2,
        )
        repository = JsonMeetingRepository(settings.storage_path)
        self.__dict__.update(_build_common(settings, repository))


def build_container() -> SoloContainer | CollabContainer:
    """Factory sem cache — use em testes para obter container sempre fresco."""
    settings = get_settings()
    if settings.app_mode == AppMode.COLLAB:
        return CollabContainer()
    return SoloContainer()


@lru_cache(maxsize=1)
def get_container() -> SoloContainer | CollabContainer:
    """Singleton por processo.

    ATENÇÃO: se fizer get_settings.cache_clear() em testes,
    chame também get_container.cache_clear().
    Em testes prefira build_container() diretamente.
    """
    return build_container()