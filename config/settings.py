# Configurações da aplicação, lidas da .env com validação e tipagem forte
from pydantic_settings import BaseSettings
from functools import lru_cache

# Definindo a classe de configuração de aplicação, com validação de tipos e carregamento automático
class Settings(BaseSettings):
    openai_api_key: str
    openai_model: str = "gpt-4o"
    whisper_model: str = "whisper-1"
    whisper_language: str = "pt"
    storage_path: str = "data/meetings"
    max_audio_size_mb: int = 25  # Limite da API Whisper
  
# Configurações de ambiente para leitura do env.
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Singleton para acessar configurações em toda a aplicação sem ler. env varias vezes 
@lru_cache
def get_settings() -> Settings:
    """Singleton — lê .env uma única vez."""
    return Settings()
