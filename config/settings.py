from enum import Enum
from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field


class AppMode(str, Enum):
    SOLO = "solo"
    COLLAB = "collab"


class Settings(BaseSettings):

    # ── Modo de operação ──────────────────────────────────────────────
    app_mode: AppMode = AppMode.SOLO

    # ── OpenAI ───────────────────────────────────────────────────────
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    whisper_model: str = "whisper-1"
    whisper_language: str = "pt"

    # ── OpenRouter (alternativa ao OpenAI) ────────────────────────────
    llm_provider: str = "openai"                    # "openai" ou "openrouter"
    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-4o"
    openrouter_site_url: str = ""
    openrouter_site_name: str = "Meet Agent"

    # ── Storage ───────────────────────────────────────────────────────
    storage_path: str = "data/meetings"
    database_url: str = ""
    audio_storage_path: str = "data/audio"
    s3_bucket: str = ""

    # ── Fila e API (modo collab) ──────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    secret_key: str = "dev-secret-change-in-prod"
    allowed_origins: list[str] = Field(default=["http://localhost:8501"])

    # ── Áudio ─────────────────────────────────────────────────────────
    max_audio_size_mb: int = 25

    # ── Diarização real (pyannote) ────────────────────────────────────
    use_real_diarization: bool = False
    huggingface_token: str = ""
    diarization_device: str = "cpu"

    # ── Reunião ───────────────────────────────────────────────────────
    default_meeting_type: str = "general"

    # ── Google Calendar (Fase 6) ──────────────────────────────────────
    enable_calendar: bool = False
    google_credentials_path: str = "credentials.json"
    google_token_path: str = "token.json"

    # ── Properties ───────────────────────────────────────────────────

    @property
    def is_solo(self) -> bool:
        return self.app_mode == AppMode.SOLO

    @property
    def is_collab(self) -> bool:
        return self.app_mode == AppMode.COLLAB

    @property
    def is_openrouter(self) -> bool:
        return self.llm_provider == "openrouter"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()