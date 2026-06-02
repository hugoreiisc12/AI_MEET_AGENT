# IA Google Meet

Assistente para reunioes com transcricao, resumo automatico e chat sobre o conteudo.

## O que o projeto faz

- Transcreve audio com Whisper.
- Gera resumo estruturado com LLM (overview, topicos, tarefas, decisoes).
- Permite chat contextual sobre a reuniao.
- Suporta envio de bot para Google Meet via Playwright.
- Funciona em dois modos:
  - `solo`: fluxo local, sem fila.
  - `collab`: fluxo com API/Fila (FastAPI + Celery/Redis).

## Estrutura principal

- `config/`: configuracoes da aplicacao (`Settings`).
- `domain/`: entidades e interfaces de dominio.
- `use_cases/`: casos de uso.
- `infrastructure/`: implementacoes concretas (transcricao, llm, recorder, repositorios).
- `presentation/`: Streamlit e container de injecao de dependencia.
- `api/`: rotas FastAPI e schemas.
- `worker/`: tarefas assicronas.

## Requisitos

- Python 3.10+
- `ffmpeg` instalado no sistema
- Chave de API para o provedor LLM que voce usar (ex.: OpenAI) ou configuracao local (ex.: Ollama)

## Configuracao rapida

1. Criar e ativar ambiente virtual:

```bash
python -m venv venv
source venv/bin/activate
```

2. Instalar dependencias:

```bash
pip install -r requirements.txt
```

3. Criar/ajustar `.env` na raiz. Exemplo minimo:

```env
APP_MODE=solo
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o
WHISPER_TRANSCRIBER=api
WHISPER_MODEL=whisper-1
WHISPER_LANGUAGE=pt

STORAGE_PATH=data/meetings
AUDIO_STORAGE_PATH=data/audio
MAX_AUDIO_SIZE_MB=25

RECORDER_PROVIDER=none
BOT_GOOGLE_EMAIL=
BOT_GOOGLE_PASSWORD=
BOT_CHROME_PROFILE=./bot_chrome_profile
BOT_NAME=Meet Agent
BOT_HEADLESS=false
```

Para usar Whisper local, altere:

```env
WHISPER_TRANSCRIBER=local
WHISPER_LOCAL_MODEL=medium
WHISPER_DEVICE=cpu
```

Notas:
- Para usar bot no Meet, defina `RECORDER_PROVIDER=playwright` e credenciais do bot.
- O projeto também suporta LLM local via variáveis como `LLM_PROVIDER` e `OLLAMA_*`.
- Whisper local requer `pip install openai-whisper torch`.

## Executando

### Streamlit

```bash
streamlit run main.py
```

### API

```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### Worker (modo collab)

```bash
celery -A worker.tasks worker --loglevel=info
```

## Bot Playwright

Se for a primeira vez com conta Google do bot, execute setup de autenticacao para salvar perfil:

```bash
python infrastructure/recorder/bot_setup.py
```

Depois, use a UI/API para enviar o bot para a reuniao.

## Checagem rapida

Checagem estatica (sem testes):

```bash
python -m pyright
```

## Observacoes

- Este repositorio pode conter duas pastas de ambiente (`venv` e `.venv`); use apenas uma para evitar inconsistencias.
- Nao versione credenciais reais no `.env`.
- Testes com `pytest` podem ser executados depois, separadamente.

## Estado atual

- Imports e nomes de modulo de recorder normalizados para `infrastructure/recorder`.
- Ajustes de tipagem aplicados em rotas/API e dashboard Streamlit.
- Dependencias de API/fila adicionadas: `fastapi`, `uvicorn`, `redis`, `celery`.

## Testes

- Executar testes com `pytest`:

```bash
pytest -q
```

- Cheque de tipagem com `pyright`:

```bash
python -m pyright
```

## Docker / Compose

- Rodar com Docker Compose (ex.: produção local):

```bash
docker compose up --build
```

- Arquivo principal: `docker-compose.yml`.

## Como empacotar (zip)

Se quiser gerar um snapshot do estado atual do projeto (excluindo ambientes virtuais), você pode rodar no diretório raiz:

```bash
zip -r IA_GOOGLE_MEET_$(date +%Y%m%d).zip . -x "*/.venv/*" "*/venv/*" "*.pyc" "__pycache__/*" "data/*"
```

O comando acima cria um arquivo `IA_GOOGLE_MEET_YYYYMMDD.zip` no diretório atual ignorando pastas de ambiente, caches e a pasta `data` para reduzir o tamanho.

## Contato

Para dúvidas ou contribuições, abra uma issue ou PR neste repositório.

