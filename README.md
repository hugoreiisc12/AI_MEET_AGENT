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
- `ffmpeg` instalado no sistema (dependência de áudio/Whisper local)
- Chave de API para o provedor LLM que voce usar (ex.: OpenAI) ou configuração local (ex.: Ollama)

## Dependências do sistema por SO

### macOS

- `Homebrew`
- `brew install ffmpeg portaudio`
- `pip install -r requirements.txt`
- Para o Playwright, depois: `playwright install chromium`

### Linux (Debian/Ubuntu)

- `sudo apt update`
- `sudo apt install ffmpeg libsndfile1 portaudio19-dev python3-pyaudio`
- `pip install -r requirements.txt`
- Para o Playwright, depois: `playwright install chromium`

### Windows

- Instale Python 3.10+ de https://www.python.org/
- Instale FFmpeg e adicione `ffmpeg` ao PATH
- `pip install -r requirements.txt`
- Para o Playwright, depois: `playwright install chromium`
- Se encontrar erro de compilação de pacotes nativos, instale o Build Tools do Visual Studio ou use as rodas pré-compiladas.

## Dependências Python principais

O pacote base usado pelo projeto está em `requirements.txt`:

- `openai`, `langchain`, `langchain-openai`
- `google-auth`, `google-auth-oauthlib`, `google-api-python-client`
- `pydantic-settings`, `python-dotenv`
- `fastapi`, `uvicorn`, `redis`, `celery`, `requests`
- `streamlit`, `playwright`, `pyaudio`

Para o modo colaborativo, rode também:

```bash
pip install -r requirements-collab.txt
```

Para diarização real e Whisper local avançado, rode:

```bash
pip install -r requirements_diarization.txt
```

Se usar Whisper local sem diarização, instale:

```bash
pip install openai-whisper torch
```

## Configuração rapida

1. Criar e ativar ambiente virtual:

```bash
python -m venv venv
source venv/bin/activate
```

2. Instalar dependencias:

```bash
pip install -r requirements.txt
```

3. Criar/ajustar `.env` na raiz. Exemplo minimo para **Solo**:

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
```

Para usar Whisper local, altere:

```env
WHISPER_TRANSCRIBER=local
WHISPER_LOCAL_MODEL=medium
WHISPER_DEVICE=cpu
```

---

## Fluxo de Execução por Modo

### Modo Solo

Fluxo local simples (sem fila, sem API):

```bash
streamlit run main.py
```

- Faça upload de um arquivo de áudio
- Processamento acontece na hora
- Resultado aparece imediatamente no histórico

**Quando usar:** desenvolvimento local, testes, reuniões pontuais.

### Modo Colaborativo (Collab) — Windows / macOS / Linux

Fluxo com API, Fila e Bot Playwright (requer Redis, Celery, FastAPI).

#### 1. Preparar ambiente

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# Windows CMD
.venv\Scripts\activate.bat
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
pip install -r requirements-collab.txt
python -m playwright install chromium
```

#### 2. Instalar Redis

**macOS (Homebrew):**
```bash
brew install redis
```

**Windows (Chocolatey):**
```powershell
choco install redis-64
```

**Windows (WSL):**
```bash
wsl
sudo apt install redis-server
redis-server
```

#### 3. Configurar `.env` para collab

```env
APP_MODE=collab
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/meetagent
REDIS_URL=redis://localhost:6379/0
API_HOST=127.0.0.1
API_PORT=8000

RECORDER_PROVIDER=playwright
BOT_GOOGLE_EMAIL=seubot@gmail.com
BOT_GOOGLE_PASSWORD=sua_senha
BOT_CHROME_PROFILE=./bot_chrome_profile
BOT_HEADLESS=false

LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=nemotron-mini
```

#### 4. Autenticar bot (primeira vez)

```bash
python infrastructure/recorder/bot_setup.py
```

- Abre o navegador de forma visível
- Você faz o login manualmente (ou confirma 2FA)
- O perfil é salvo em `BOT_CHROME_PROFILE`

#### 5. Iniciar serviços em 4 terminais

**Terminal 1 — Redis:**
```bash
redis-server
```

**Terminal 2 — API FastAPI:**
```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

**Terminal 3 — Worker Celery:**
```bash
celery -A worker.tasks worker --loglevel=info
```

**Terminal 4 — Streamlit:**
```bash
streamlit run main.py
```

Se usar Ollama para LLM local, **Terminal 5:**
```bash
ollama serve
```

#### 6. Usar a aplicação

- Abra http://localhost:8501
- Confirme que está em modo "Colaborativo"
- Cole o link do Google Meet
- Clique em "Enviar bot para a reunião"
- O bot entra automaticamente e grava o áudio
- Quando a reunião termina, o processamento é automático

---

## Meeting ID e Histórico

Cada reunião processada recebe um `meeting_id` único (UUID) que é:

- **Exibido no histórico:** no sidebar, junto ao título da reunião (8 caracteres truncados)
- **Mostrado nos detalhes:** abaixo do título quando a reunião é carregada
- **Copiável:** você pode usar o ID para buscar a reunião depois

Exemplo:
```
📋 Sprint Planning — 550e8400
Meeting ID: `550e8400-e29b-41d4-a716-446655440000`
```

---

## Configuração da LLM para Chat

Quando você carrega uma reunião e faz perguntas, o sistema usa uma LLM configurada como **especialista em reuniões**.

### LLM Padrão: OpenAI (com custo)

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sua_chave_aqui
OPENAI_MODEL=gpt-4o
```

Requer chave de API do OpenAI. Respostas rápidas, modelo mais capaz.

### LLM Local: Ollama (sem custo, roda offline)

Para usar uma LLM local gratuita:

1. Instale Ollama: https://ollama.ai

2. Configure no `.env`:
   ```env
   LLM_PROVIDER=ollama
   OLLAMA_BASE_URL=http://localhost:11434/v1
   OLLAMA_MODEL=nemotron-mini
   ```

3. Em outro terminal, inicie o Ollama:
   ```bash
   ollama serve
   ```

4. Puxe o modelo pela primeira vez:
   ```bash
   ollama pull nemotron-mini
   ```

5. Ao fazer perguntas no chat, a LLM local responderá como especialista em reuniões.

### Alternativa: OpenRouter (acesso a múltiplos modelos)

```env
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sua_chave
OPENROUTER_MODEL=openai/gpt-4o
OPENROUTER_SITE_URL=https://seu-site.com
OPENROUTER_SITE_NAME=Meet Agent
```

---

## Chat com Reunião

Quando você carrega uma reunião processada:

1. **Transcrição carregada:** o texto completo da reunião fica disponível como contexto
2. **Sistema prompt especialista:** a LLM recebe instruções para responder como assistente de reuniões
3. **Você faz uma pergunta:** ex "Quem ficou responsável pela tarefa X?"
4. **LLM responde** baseada na transcrição:
   - Cita a fonte quando possível (ex: "Conforme mencionado por Speaker 0...")
   - Responde "Isso não foi mencionado" se não tiver informação
   - Mantém histórico da conversa

**Exemplos de pergunta:**
```
"Quem ficou responsável pelas tarefas?"
"Qual foi o principal tópico discutido?"
"Qual era o prazo mencionado?"
"Resuma as decisões tomadas"
```

---

## Bot Playwright

Permite enviar um bot automático para o Google Meet e gravar áudio.

Se for a primeira vez com conta Google do bot, execute o setup:

```bash
python infrastructure/recorder/bot_setup.py
```

- Abre o navegador de forma visível
- Você faz o login manualmente (ou confirma 2FA)
- O perfil é salvo em `BOT_CHROME_PROFILE` para uso posterior

Depois, use a UI do Streamlit (modo collab) para enviar o bot para a reunião.

## Checagem rapida

Checagem estatica (sem testes):

```bash
python -m pyright
```

## Observacoes

- Este repositorio pode conter duas pastas de ambiente (`venv` e `.venv`); use apenas uma para evitar inconsistencias.
- Nao versione credenciais reais no `.env`.
- Testes com `pytest` podem ser executados depois, separadamente.
- Para bot em modo collab, sempre execute `python infrastructure/recorder/bot_setup.py` uma vez.

## Estado atual

- Imports e nomes de modulo de recorder normalizados para `infrastructure/recorder`.
- Ajustes de tipagem aplicados em rotas/API e dashboard Streamlit.
- Dependencias de API/fila adicionadas: `fastapi`, `uvicorn`, `redis`, `celery`.
- Meeting ID exibido no histórico e detalhes de reunião.
- Chat com LLM especialista em reuniões (OpenAI, Ollama ou OpenRouter).
- Modo collab com Playwright bot recorder totalmente funcional.
- Suporte completo para Windows, macOS e Linux.

## Troubleshooting

### Windows: "redis-server não encontrado"

Se usar WSL (Windows Subsystem for Linux):
```bash
# No WSL
wsl
redis-server
```

Ou instale Redis via Chocolatey:
```powershell
choco install redis-64
```

### Windows: Playwright não encontra Chromium

```powershell
python -m playwright install chromium
```

### Bot não entra na reunião

- Confirme `RECORDER_PROVIDER=playwright`
- Confirme `BOT_GOOGLE_EMAIL` e `BOT_GOOGLE_PASSWORD` no `.env`
- Confirme que `python infrastructure/recorder/bot_setup.py` foi executado
- Confirme que `BOT_CHROME_PROFILE` existe e contém cookies de login

### Reunião não aparece no histórico após processamento

- Verifique logs do Celery: há erro no processamento?
- Verifique pasta `data/meetings`: há arquivo JSON?
- Confirme que `REDIS_URL` e `DATABASE_URL` estão corretos

### Chat não responde

- Confirme que a reunião foi carregada e processada
- Verifique se `LLM_PROVIDER` está configurado corretamente
- Se for OpenAI, verifique `OPENAI_API_KEY`
- Se for Ollama, confirme que `ollama serve` está rodando
- Verifique logs do terminal Streamlit

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

