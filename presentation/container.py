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
    Instancia o transcriber correto baseado em USE_REAL_DIARIZATION no .env.

    - False (padrão): WhisperTranscriber com pseudo-diarização por pausa
    - True: WhisperWithDiarization — Whisper + pyannote.audio (requer HUGGINGFACE_TOKEN)
    """
    if settings.use_real_diarization:
        from infrastructure.transcriber.whisper_with_diarization import WhisperWithDiarization
        return WhisperWithDiarization()

    from infrastructure.transcriber.whisper_transcriber import WhisperTranscriber
    return WhisperTranscriber()


def _build_common(settings, repository) -> dict:
    """
    Monta os componentes compartilhados entre Solo e Collab.
    Elimina duplicação — qualquer mudança feita aqui vale para os dois modos.
    """
    transcriber = _build_transcriber(settings)
    llm         = LangChainLLMService()

    # Use cases principais
    transcribe_meeting = TranscribeMeetingUC(transcriber)
    summarize_meeting  = SummarizeMeetingUC(llm, repository)
    chat_with_meeting  = ChatWithMeetingUC(llm)

    # Fase 6 — sentimento
    from infrastructure.llm.sentiment_analyzer import SentimentAnalyzer
    sentiment_analyzer = SentimentAnalyzer(llm_client=llm._llm)
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

    # Bot de reunião (substitui extensão Chrome)
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
    """
    Modo individual — tudo local, sem dependências externas.
    Funciona sem Docker, sem banco, sem Redis.
    """

    # Explicit attributes for static analysis and autocompletion
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
    """
    Modo colaborativo — Postgres + Celery.
    Requer: DATABASE_URL e REDIS_URL no .env.

    Nota: PostgresMeetingRepository ainda não implementado.
    Usa JsonMeetingRepository como fallback com aviso.
    """

    # Explicit attributes for static analysis and autocompletion
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
    """Factory — instancia o container correto baseado no APP_MODE.

    Use esta função em testes quando precisar de um container fresco
    a cada execução, sem depender do cache de get_container().
    """
    settings = get_settings()
    if settings.app_mode == AppMode.COLLAB:
        return CollabContainer()
    return SoloContainer()


@lru_cache(maxsize=1)
def get_container() -> SoloContainer | CollabContainer:
    """Singleton por processo — retorna sempre o mesmo container.

    ATENÇÃO: o cache sobrevive a mudanças em get_settings(). Se em testes
    você fizer get_settings.cache_clear(), chame também get_container.cache_clear()
    para forçar a criação de um novo container com as settings atualizadas.

    Em testes, prefira build_container() diretamente para evitar estado compartilhado:

        container = build_container()  # sempre novo, sem cache
    """
    return build_container()