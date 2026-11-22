from enum import Enum
from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field, model_validator


class AppMode(str, Enum):
    SOLO = "solo"
    COLLAB = "collab"


class Settings(BaseSettings):

    # ── Modo de operação ──────────────────────────────────────────────
    app_mode: AppMode = AppMode.SOLO

    # ── OpenAI ───────────────────────────────────────────────────────
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    # Qualquer servidor compatível com a API da OpenAI (vLLM, LM Studio, Groq...); vazio = OpenAI.
    openai_base_url: str = ""
    whisper_model: str = "whisper-1"        # usado pelo WhisperTranscriber (API)
    whisper_language: str = "pt"

    # ── Whisper Local ─────────────────────────────────────────────────
    # Usado pelo WhisperLocalTranscriber (roda na máquina, sem API)
    # WHISPER_TRANSCRIBER=local no .env ativa este modo
    whisper_transcriber: str = "api"        # "api" | "local"
    whisper_local_model: str = "medium"     # tiny | base | small | medium | large | large-v2 | large-v3
    whisper_device: str = "cpu"             # "cpu" | "cuda"
    # Termos extras (separados por vírgula) que o Whisper deve escrever certo: nomes, siglas, produtos.
    whisper_vocabulary: str = ""

    # ── Storage ───────────────────────────────────────────────────────
    storage_path: str = "data/meetings"
    mongo_uri: str = "mongodb://mongo:27017/meetagent"
    mongo_db: str = "meetagent"
    audio_storage_path: str = "data/audio"
    documents_path: str = "data/documents"   # arquivos gerados pelo chat (create_document)

    # ── Cache e API ───────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    api_port: int = 8000
    allowed_origins: list[str] = Field(default=["http://localhost:8080", "http://localhost:5173"])
    # Chave exigida no cabeçalho X-API-Key (ADR-007). Obrigatória em collab.
    api_key: str = ""
    # Login de usuários (ADR-011)
    session_days: int = 30
    allow_registration: bool = True
    max_upload_mb: int = 500
    capture_max_chunk_mb: int = 10
    capture_max_session_mb: int = 1024
    # Concorrência (ADR-015)
    api_workers: int = 1                 # processos do uvicorn
    chat_max_concurrent: int = 2         # chamadas de chat ao LLM ao mesmo tempo, por processo da API
    rate_limit_per_minute: int = 30      # envios, bots e perguntas por usuário por minuto (0 = sem limite)

    # ── Áudio ─────────────────────────────────────────────────────────
    max_audio_size_mb: int = 25

    # ── Diarização ────────────────────────────────────────────────────
    use_real_diarization: bool = False
    huggingface_token: str = ""
    diarization_device: str = "cpu"

    # ── Google Calendar ───────────────────────────────────────────────
    # Em data/google (fora do git e montado nos containers). Login uma vez, no computador:
    # python -m infrastructure.calendar.calendar_setup
    google_credentials_path: str = "data/google/credentials.json"
    google_token_path: str = "data/google/token.json"
    enable_calendar: bool = False

    # ── Provider LLM ─────────────────────────────────────────────────
    llm_provider: str = "openai"            # "openai" | "ollama" | "openrouter"
    # Contrato do agente (ADR-014): vai inteiro no prompt de sistema do chat e do resumo.
    agent_contract_path: str = "SPEC_CONTRACT.md"
    # Memória do agente e contrato v2 (ADR-022). false volta ao comportamento da v1.0: contrato v1, sem
    # índice de trechos, sem falas de outras reuniões, sem cache de respostas.
    memory_v2: bool = True
    agent_contract_v2_path: str = "SPEC_CONTRACT_V2.md"          # resumo
    agent_chat_contract_path: str = "SPEC_CONTRACT_CHAT_V2.md"   # chat (compacto, ~2,2 mil tokens)

    # Quanto de transcrição cabe num único pedido ao LLM (caracteres; ~2,6 por
    # token em português, medido na ADR-010). Acima disso o resumo é feito em
    # partes e o chat recebe só os trechos relevantes.
    llm_context_chars: int = 30000

    # Perfil do modelo (ADR-022): o mesmo grafo serve qualquer provider. 0 = janela padrão do
    # provider (OLLAMA_NUM_CTX_MAX no Ollama, 128k nos hospedados). Sem ferramenta nativa, as
    # ferramentas vão por JSON; sem modo JSON, o JSON é pedido no texto.
    llm_context_tokens: int = 0
    llm_native_tools: bool = True
    llm_json_mode: bool = True

    # Embeddings da memória do agente (ADR-022). "onnx" roda no próprio processo, igual em
    # Linux, macOS e Windows, sem serviço externo. Trocar de modelo exige reindexar.
    embedding_provider: str = "onnx"        # "onnx" | "ollama" | "openai"
    embedding_model: str = "intfloat/multilingual-e5-small"

    # Ollama (local)
    # Teto da janela pedida ao Ollama; o padrão dele (4096) corta reuniões em silêncio.
    # Janela de contexto do Ollama, a mesma em todo pedido (ADR-021): trocar de janela recarrega
    # o modelo (~50 s). 32k cobre chat e resumo de reunião longa; ~7 GB com qwen2.5:7b.
    ollama_num_ctx_max: int = 32768
    ollama_keep_alive: str = "30m"     # quanto tempo o modelo fica carregado sem uso
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "nemotron-mini"

    # OpenRouter
    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-4o"
    openrouter_site_url: str = ""
    openrouter_site_name: str = "Meet Agent"

    # ── Bot de reunião ────────────────────────────────────────────────
    bot_chrome_profile: str = "./bot_chrome_profile"
    bot_name: str = "Meet Agent"
    bot_headless: bool = False
    # Diagnóstico: salva amostras do DOM do Meet em data/audio/<id>.dom.jsonl (Sprint 2B)
    bot_debug_dom: bool = False
    # Endereço da API visto pelo navegador do bot (vazio = http://127.0.0.1:API_PORT)
    capture_endpoint: str = ""
    # Credenciamento pela interface (botão "Credenciar bot"). Com e-mail e senha da conta do bot,
    # o login é tentado sozinho; sem eles, ou se o Google pedir verificação, alguém conclui pela
    # tela do bot (noVNC) em BOT_VNC_URL.
    bot_google_email: str = ""
    bot_google_password: str = ""
    bot_vnc_url: str = "http://localhost:6080/vnc.html?autoconnect=true&resize=scale"

    # ── SMTP / E-mail ─────────────────────────────────────────────────
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    # Quem recebe o alerta de /health fora do ar (scripts/health_alert.py, S11-4)
    alert_email: str = ""

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
    def email_enabled(self) -> bool:
        return bool(self.smtp_user and self.smtp_password)

    @property
    def capture_url(self) -> str:
        return self.capture_endpoint or f"http://127.0.0.1:{self.api_port}"

    @property
    def use_local_whisper(self) -> bool:
        return self.whisper_transcriber == "local"

    @model_validator(mode="after")
    def _validate_collab(self) -> "Settings":
        """Em produção (collab), falha na partida em vez de falhar no meio de uma reunião."""
        if not self.is_collab:
            return self
        missing = []
        if not self.mongo_uri:
            missing.append("MONGO_URI")
        if not self.redis_url:
            missing.append("REDIS_URL")
        if not self.api_key:
            missing.append("API_KEY")
        if not self.use_local_whisper and not self.openai_api_key:
            missing.append("OPENAI_API_KEY (ou WHISPER_TRANSCRIBER=local)")
        if self.llm_provider == "openai" and not self.openai_api_key and not self.openai_base_url:
            missing.append("OPENAI_API_KEY (LLM_PROVIDER=openai)")
        if self.llm_provider == "openrouter" and not self.openrouter_api_key:
            missing.append("OPENROUTER_API_KEY")
        if missing:
            raise ValueError("APP_MODE=collab exige no .env: " + ", ".join(dict.fromkeys(missing)))
        return self

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",  # Ignora campos extras do .env
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()