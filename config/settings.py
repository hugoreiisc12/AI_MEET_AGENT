from enum import Enum
from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field


# Enum para definir os modos de funcionamento da aplicação
class AppMode(str, Enum):
    SOLO = "solo"  # Modo solo sem colaboração
    COLLAB = "collab"  # Modo colaborativo


# Classe principal de configurações com validação de tipos via Pydantic
class Settings(BaseSettings):
    # Modo de operação da aplicação
    app_mode: AppMode = AppMode.SOLO

    # Configurações OpenAI para API
    openai_api_key: str  # Chave de API obrigatória
    openai_model: str = "gpt-4o"  # Modelo GPT para resumo e chat
    whisper_model: str = "whisper-1"  # Modelo para transcrição de áudio
    whisper_language: str = "pt"  # Idioma padrão (português)

    # Paths de armazenamento
    storage_path: str = "data/meetings"  # Diretório para salvar reuniões
    database_url: str = ""  # URL do banco de dados (opcional)
    audio_storage_path: str = "data/audio"  # Diretório para áudios
    s3_bucket: str = ""  # Bucket S3 para storage em nuvem (opcional)

    # Configurações de cache e API
    redis_url: str = "redis://localhost:6379/0"  # Conexão Redis para cache
    
    api_host: str = "0.0.0.0"  # Host da API
    api_port: int = 8000  # Porta da API
    secret_key: str = "dev-secret-change-in-prod"  # Chave secreta (mudar em produção)
    allowed_origins: list[str] = Field(default=["http://localhost:8501"])  # CORS permitido

    max_audio_size_mb: int = 25

    use_real_diarization: bool = False
    huggingface_token: str = ""
    diarization_device: str = "cpu"
    default_meeting_type: str = "general"
    google_credentials_path: str = "credentials.json"
    google_token_path: str = "token.json"
    enable_calendar: bool = False  # Limite máximo de tamanho de áudio

    # Propriedade para verificar se é modo solo
    @property
    def is_solo(self) -> bool:
        return self.app_mode == AppMode.SOLO

    # Propriedade para verificar se é modo colaborativo
    @property
    def is_collab(self) -> bool:
        return self.app_mode == AppMode.COLLAB

    # Configuração de Pydantic para carregar variáveis do arquivo .env
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


# Singleton com cache - retorna a mesma instância de Settings em toda a aplicação
@lru_cache
def get_settings() -> Settings:
    return Settings()