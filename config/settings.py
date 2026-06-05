from enum import Enum
from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field


class AppMode(str, Enum):
    SOLO = "solo"
    COLLAB = "collab"


class Settings(BaseSettings):

    #  Modo de operação 
    app_mode: AppMode = AppMode.SOLO

    #  OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    whisper_model: str = "whisper-1"     
    whisper_language: str = "pt"

    # ── Whisper Local ─────────────────────────────────────────────────
    # Usado pelo WhisperLocalTranscriber (roda na máquina, sem API)
    # WHISPER_TRANSCRIBER=local no .env ativa este modo
    whisper_transcriber: str = "api"        # "api" | "local"
    whisper_local_model: str = "medium"     # tiny | base | small | medium | large | large-v2 | large-v3
    whisper_device: str = "cpu"             # "cpu" | "cuda"

    # ── Storage ───────────────────────────────────────────────────────
    storage_path: str = "data/meetings"
    repository_path: str = "data/meetings.db"
    database_url: str = ""
    audio_storage_path: str = "data/audio"
    s3_bucket: str = ""

    # ── Cache e API ───────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    secret_key: str = "dev-secret-change-in-prod"
    allowed_origins: list[str] = Field(default=["http://localhost:8501"])

    # ── Áudio ─────────────────────────────────────────────────────────
    max_audio_size_mb: int = 25

    # ── Diarização ────────────────────────────────────────────────────
    use_real_diarization: bool = False
    huggingface_token: str = ""
    diarization_device: str = "cpu"

    # ── Reunião ───────────────────────────────────────────────────────
    default_meeting_type: str = "general"

    # ── Google Calendar ───────────────────────────────────────────────
    google_credentials_path: str = "credentials.json"
    google_token_path: str = "token.json"
    enable_calendar: bool = False

    # ── Provider LLM ─────────────────────────────────────────────────
    llm_provider: str = "ollama"
    llm_temperature: float = 0.0
    llm_top_p: float = 1.0

    # Ollama (local)
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "nemotron-mini"

    # OpenRouter
    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-4o"
    openrouter_site_url: str = ""
    openrouter_site_name: str = "Meet Agent"

    # ── Bot de reunião ────────────────────────────────────────────────
    recorder_provider: str = "none"
    bot_google_email: str = ""
    bot_google_password: str = ""
    bot_chrome_profile: str = "./bot_chrome_profile"
    bot_name: str = "Meet Agent 🤖"
    bot_headless: bool = False
    notification_email: str = ""
    enable_email: bool = False

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

    @property
    def is_ollama(self) -> bool:
        return self.llm_provider == "ollama"

    @property
    def use_local_whisper(self) -> bool:
        return self.whisper_transcriber == "local"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()