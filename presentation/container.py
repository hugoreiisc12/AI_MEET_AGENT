"""
container.py — Injeção de dependência com suporte a dois modos.

SoloContainer  → uso individual: JSON local, sem fila, Streamlit direto.
CollabContainer → uso colaborativo: Postgres, Celery, FastAPI + Streamlit.

A factory get_container() decide qual usar via APP_MODE no .env.
"""

from functools import lru_cache
from config.settings import get_settings, AppMode

from infrastructure.transcriber.whisper_transcriber import WhisperTranscriber
from infrastructure.llm.langchain_llm_service import LangChainLLMService   # ← corrigido
from infrastructure.json_meeting_repository import JsonMeetingRepository

from use_cases.transcribe_meeting import TranscribeMeetingUC
from use_cases.summarize_meeting import SummarizeMeetingUC
from use_cases.chat_with_meeting import ChatWithMeetingUC
from use_cases.analyze_sentiment import AnalyzeSentimentUC
from use_cases.fetch_meeting_context import FetchMeetingContextUC


def _build_common(settings, repository) -> dict:
    """
    Monta os componentes compartilhados entre Solo e Collab.
    Elimina duplicação — qualquer mudança feita aqui vale para os dois modos.
    """
    transcriber = WhisperTranscriber()
    llm         = LangChainLLMService()

    # Use cases principais
    transcribe_meeting = TranscribeMeetingUC(transcriber)
    summarize_meeting  = SummarizeMeetingUC(llm, repository)
    chat_with_meeting  = ChatWithMeetingUC(llm)

    # Fase 6 — sentimento
    from infrastructure.llm.sentiment_analyzer import SentimentAnalyzer
    sentiment_analyzer = SentimentAnalyzer(llm_client=llm)   # ← passa o service, não ._llm
    analyze_sentiment  = AnalyzeSentimentUC(analyzer=sentiment_analyzer)

    # Fase 6 — calendar (opcional via .env)
    fetch_meeting_context = None
    if getattr(settings, "enable_calendar", False):
        from infrastructure.calendar.google_calendar_service import GoogleCalendarService
        calendar = GoogleCalendarService(
            credentials_path=getattr(settings, "google_credentials_path", "credentials.json"),
            token_path=getattr(settings, "google_token_path", "token.json"),
        )
        fetch_meeting_context = FetchMeetingContextUC(calendar)

    return {
        "_transcriber":         transcriber,
        "_llm":                 llm,
        "_repository":          repository,
        "transcribe_meeting":   transcribe_meeting,
        "summarize_meeting":    summarize_meeting,
        "chat_with_meeting":    chat_with_meeting,
        "analyze_sentiment":    analyze_sentiment,
        "fetch_meeting_context": fetch_meeting_context,
        "repository":           repository,
    }


class SoloContainer:
    """
    Modo individual — tudo local, sem dependências externas.
    Funciona sem Docker, sem banco, sem Redis.
    """

    def __init__(self) -> None:
        settings   = get_settings()
        repository = JsonMeetingRepository(storage_path=settings.storage_path)
        self.__dict__.update(_build_common(settings, repository))


class CollabContainer:
    """
    Modo colaborativo — Postgres + Celery.
    Requer: DATABASE_URL e REDIS_URL no .env.

    Nota: PostgresMeetingRepository ainda não implementado.
    Usa JsonMeetingRepository como fallback com aviso.
    """

    def __init__(self) -> None:
        import warnings
        settings = get_settings()

        if not settings.database_url:
            raise RuntimeError(
                "APP_MODE=collab requer DATABASE_URL no .env.\n"
                "Exemplo: DATABASE_URL=postgresql+asyncpg://user:pass@localhost/meetagent"
            )

        # TODO: trocar por PostgresMeetingRepository quando implementado
        warnings.warn(
            "CollabContainer usando JsonMeetingRepository (storage local). "
            "Implemente PostgresMeetingRepository para produção real.",
            stacklevel=2,
        )
        repository = JsonMeetingRepository(settings.storage_path)
        self.__dict__.update(_build_common(settings, repository))


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