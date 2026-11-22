# Meet Agent

Bot que entra em reuniões (Google Meet; Teams e Zoom em validação), grava o áudio, transcreve,
identifica quem falou, gera um resumo com tarefas e decisões e responde perguntas sobre a reunião.
Cada usuário tem a própria conta e vê só as próprias reuniões.

Decisões de arquitetura: [docs/adr/README.md](docs/adr/README.md). Roteiro: [docs/roadmap.md](docs/roadmap.md).

## Como funciona

```
Interface / API ──► fila "bot" ──► container do bot ──► Chromium entra no Meet
                                        │  áudio em chunks ──► API /capture ──► data/audio/<id>.webm
                                        │  legendas e presentes ──► data/audio/<id>.speakers.jsonl
                                        ▼
                    fila "celery" ──► worker de processamento ──► Whisper ──► nomes ──► LLM ──► MongoDB
```

- O agente (resumo e chat) é um grafo LangGraph regido pelo contrato `SPEC_CONTRACT.md`: cada
  resposta do chat é conferida contra regras do contrato antes de chegar ao usuário (ADR-014).
  As decisões saem classificadas: aprovada, proposta, pendente etc.
- Um único pipeline (`use_cases/process_meeting.py`) faz áudio → transcrição → resumo e grava o
  status a cada etapa: `pending`, `recording`, `transcribing`, `summarizing`, `done`, `error`.
- O texto vem do Whisper. As legendas do Meet são usadas só para saber **quem** falou e quando.
- O bot entra com microfone e câmera desligados: só escuta.

| Pasta | Conteúdo |
|-------|----------|
| `domain/` | Entidades e interfaces (portas) |
| `use_cases/` | Regras: pipeline, resumo, chat, alinhamento de falantes |
| `infrastructure/` | Whisper, LLM, repositórios, bot (`recorder/`), e-mail, exportação, agenda |
| `frontend/` | Interface (React/Vite): login, Estúdio, Gravações, Observabilidade, Minha conta |
| `presentation/` | `container.py` (única composição) e a interface Streamlit antiga (perfil `streamlit`) |
| `api/` | FastAPI |
| `worker/` | Tasks Celery |

## Subir o ambiente (produção local)

Tudo roda em containers (ADR-016): API, interface, workers, MongoDB, Redis e o **bot**
(Chromium com tela virtual e som virtual, login da conta do Google num volume). Não precisa de
Python, Playwright nem Chromium no host.

Pré-requisitos: Docker Desktop e [Ollama](https://ollama.com) no host com o modelo configurado
(`ollama pull qwen2.5:7b`). Confira `df -h`: o build das duas imagens precisa de espaço livre.

```bash
cp .env.example .env     # preencha; API_KEY é obrigatória (comando para gerar está no arquivo)

# Sobe a interface :8080, api :8001, workers, redis :6380, mongo :27018 e o bot (noVNC :6080)
docker compose --profile bot up -d --build --remove-orphans
```

1. Abra http://localhost:8080 e crie sua conta (a primeira é a de administrador e herda as
   reuniões que já existiam).
2. Na tela **Enviar bot**, clique em **🤖 Credenciar bot**. Com `BOT_GOOGLE_EMAIL` e
   `BOT_GOOGLE_PASSWORD` no `.env` ele tenta entrar sozinho; sem eles, ou se o Google pedir
   verificação, a tela do navegador do bot aparece na própria página (noVNC) para você concluir
   o login. Ao terminar: "✅ Bot credenciado". O login fica salvo no volume `bot_profile`.
3. Cole o link da reunião e envie o bot. Quem organiza a reunião precisa **admitir** o bot quando
   ele pedir para entrar. A tela acompanha o andamento sozinha.

Depois de atualizar o código: `docker compose --profile bot up -d --build --remove-orphans`. O mesmo
comando constrói a API e a interface, sobe tudo e indexa as reuniões para a memória do agente
(serviço `memory-index`, que roda e termina; acompanhe com `docker compose logs -f memory-index`).
Sem `--profile bot` o bot não sobe e o envio fica bloqueado.

**Vários usuários ao mesmo tempo (ADR-015).** Transcrição e resumo têm filas e workers próprios
(`worker-transcribe`, `worker-llm`); o 1º envio de cada usuário passa na frente do 2º de qualquer
outro. Mais paralelismo: `docker compose up -d --scale worker-transcribe=2` (cada um carrega o
Whisper na memória). O container do bot grava uma reunião por vez; o worker do host
(modo de desenvolvimento, abaixo) permite um bot por perfil de Chrome.

Teste de carga, sempre contra um banco de rascunho com cadastro aberto:
`python -m scripts.load_test --api http://localhost:8001 --audio reuniao.wav --uploads 4,1,1`.

### Acessar de outro aparelho da mesma rede

A interface e a API ficam abertas na rede local: no celular ou em outro computador no mesmo Wi-Fi,
abra `http://<ip-desta-máquina>:8080` (no macOS: `ipconfig getifaddr en0`) ou
`http://<nome-da-máquina>.local:8080`. O IP pode mudar quando o roteador renova o endereço.
Mongo, Redis e a tela do bot (noVNC, porta 6080) ficam só nesta máquina, porque não têm senha:
por isso o **credenciamento do bot** é feito a partir desta máquina. É HTTP sem criptografia;
fora da rede de casa ou do escritório, use o compose de produção com HTTPS.

### O bot em container

O serviço `bot` (perfil `bot` do compose, `Dockerfile.bot`) consome a fila "bot" e guarda o login
do Google no volume `bot_profile`. Para ver o que ele está vendo durante uma reunião, ou concluir
um login que o Google pediu: http://localhost:6080/vnc.html (a porta só abre nesta máquina).

Alternativas ao botão **Credenciar bot** e testes pelo terminal:

```bash
# Login manual, uma vez: abra http://localhost:6080/vnc.html, clique em Connect e entre na conta
docker compose --profile bot run --rm --service-ports bot python -m infrastructure.recorder.bot_setup
# Fumaça: alguém cria a reunião e admite o bot
docker compose --profile bot run --rm --service-ports bot python -m infrastructure.recorder.run_bot --url <link> --smoke 30
```

### Windows (Docker Desktop + WSL2)

Tudo que roda no compose funciona igual no Windows: envio de áudio, transcrição, resumo, chat,
login e backup. O bot roda pelo container (`--profile bot`); no Windows falta a primeira reunião real.

1. Instale o WSL2 (`wsl --install` no PowerShell como administrador) e o Docker Desktop com o
   backend WSL2 (padrão). Em *Settings → Resources → WSL integration*, ligue a sua distribuição.
2. **Clone dentro do WSL2**, não em `C:\`. A pasta `./data` é montada nos containers, e montagem a
   partir do disco do Windows é muito lenta para o áudio e o modelo do Whisper:
   ```bash
   # no terminal do Ubuntu (WSL2)
   cd ~ && git clone <repositório> meet-agent && cd meet-agent
   cp .env.example .env    # preencha
   docker compose --profile bot up -d --build
   ```
   O `.gitattributes` mantém os arquivos com fim de linha LF mesmo no Windows. Se o repositório
   foi clonado antes dele existir com `core.autocrlf=true` e algum script falhar com `$'\r'`,
   rode `git add --renormalize . && git checkout -- .` (ou clone de novo).
3. **Ollama no Windows** (instalador do site): os containers o acessam em
   `host.docker.internal:11434`, já configurado no compose. Se o resumo der erro de conexão,
   defina a variável de ambiente `OLLAMA_HOST=0.0.0.0` no Windows e reinicie o Ollama.
4. Abra http://localhost:8080 no navegador do Windows (o Docker Desktop publica as portas).

Backup e restauração: `docker compose run --rm backup` e
`docker compose run --rm backup restore backups/<arquivo>`, no terminal do WSL2 ou no PowerShell.

### Modo de desenvolvimento

**Bot no host** (alternativa ao container, útil para depurar; usa o Chromium e o login desta
máquina). **Não rode junto com o container do bot**: os dois pegam tarefas da mesma fila.

```bash
docker compose up -d --build                    # sem --profile bot
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
playwright install chromium
python -m infrastructure.recorder.bot_setup     # uma vez: login manual da conta do bot
python main.py --bot-worker                     # deixe rodando
# um bot por perfil: BOT_CHROME_PROFILE=./bot_chrome_profile_2 (bot_setup e --bot-worker)
```

**Sem Docker**: com `APP_MODE=solo` não há fila nem MongoDB: as reuniões ficam em `data/meetings/*.json`
e as contas em `data/auth.json` (há login nos dois modos; a primeira conta de cada modo é a admin).

```bash
APP_MODE=solo API_PORT=8001 python main.py --api     # API
cd frontend && npm install && npm run dev             # interface em http://localhost:5173 (proxy /api → :8001)
python -m infrastructure.recorder.run_bot --url "https://meet.google.com/xxx-xxxx-xxx"
```

O admin troca entre solo e colaborativo pelo botão da barra lateral (rota `POST /admin/mode`). Vale
só com um processo da API (`API_WORKERS=1`) e não sobrevive a reiniciar; no compose (`API_WORKERS=2`)
troque o `APP_MODE` no `.env`. As contas de um modo não valem no outro.

## Interface (frontend/)

React/Vite em `frontend/`, recriada do repositório Interface-AI-Meet. Fala só com `/api` na mesma
origem: no desenvolvimento o Vite repassa para `VITE_API_PROXY` (padrão `http://localhost:8001`); no
compose, o container `web` (Caddy) serve os arquivos e repassa `/api` para `api:8000`. Mapa de rotas
da API para as telas: [docs/redesign/mapa-api-frontend.md](docs/redesign/mapa-api-frontend.md).

```bash
cd frontend
npm run build                         # type-check + bundle em dist/
docker compose up -d --build web      # só a interface, contra a api do compose
```

O Streamlit antigo continua no repositório, fora do padrão: `docker compose --profile streamlit up -d`.

## API

Documentação interativa (Swagger): http://localhost:8001/docs. O contrato para construir outro
front está em [docs/api/openapi.json](docs/api/openapi.json) (ADR-013).

As rotas de reunião aceitam `Authorization: Bearer <token>` (sessão de um usuário, que vê só as
próprias reuniões) ou `X-API-Key` (chave de serviço, vê tudo).

| Rota | Função |
|------|--------|
| `POST /auth/register`, `/auth/login` | Cria conta ou entra; devolvem o `token` da sessão |
| `POST /auth/logout`, `GET /auth/me` | Encerra a sessão; usuário atual |
| `GET/DELETE /auth/sessions` | Minhas sessões; encerra uma ou todas as outras |
| `POST /auth/password`, `/password/forgot`, `/password/reset` | Troca de senha e recuperação por código no e-mail |
| `GET /admin/users`, `POST /admin/sessions/purge` | Só admin (a primeira conta): usuários e limpeza de sessões |
| `GET /config` | O que está ligado: cadastro, e-mail, agenda, plataformas (sem autenticação) |
| `GET /health` | Confere banco e fila; 503 se algum não responde |
| `GET /meetings/` | Lista as reuniões do usuário |
| `GET /meetings/{id}` | Reunião completa: resumo, transcrição e conversa |
| `DELETE /meetings/{id}` | Apaga a reunião e a gravação |
| `POST /meetings/upload` | Envia um áudio para processar (teto `MAX_UPLOAD_MB`) |
| `POST /meetings/bot` | Manda o bot para um link de reunião |
| `GET /meetings/{id}/status` | Status, erro e resumo |
| `POST /meetings/{id}/process` | Reprocessa o áudio já gravado |
| `POST /meetings/{id}/chat` | Pergunta sobre a reunião (a conversa fica guardada) |
| `PATCH /meetings/{id}/tasks/{n}` | Marca ou desmarca a tarefa `n` |
| `GET /meetings/{id}/export.md` | Reunião em Markdown |
| `POST /meetings/{id}/tasks/email` | Envia as tarefas por e-mail (requer SMTP no `.env`) |
| `POST /capture/*` | Uso interno do bot; token por sessão |

```bash
curl -H "X-API-Key: $API_KEY" http://localhost:8001/meetings/
```

Depois de mudar rotas ou modelos, regenere o contrato:

```bash
docker compose run --rm --no-deps -v "$PWD/docs:/app/docs" api python -m api.export_openapi
```

## Plataformas

| Plataforma | Estado | Nome de quem fala |
|------------|--------|-------------------|
| Google Meet | Validado em reunião real | Sim (legendas) |
| Zoom | Escrito, **não validado**: rode o teste de fumaça antes de usar | Não ("Speaker N") |
| Microsoft Teams | Escrito, **não validado**: rode o teste de fumaça antes de usar | Não ("Speaker N") |
| Discord | Não suportado: exige bot oficial com token (ADR-012) | — |

No Teams e no Zoom o bot entra como convidado pelo navegador, com o nome `BOT_NAME`.

## Recursos opcionais

| Recurso | Como ligar |
|---------|------------|
| E-mail de tarefas | `SMTP_USER` e `SMTP_PASSWORD` no `.env` |
| Título pela agenda | `ENABLE_CALENDAR=true`, com `credentials.json` do Google Calendar |
| Exportação Markdown | Sempre disponível (botão na interface e rota da API) |

## Chat com ações

Além de responder, o chat executa dois pedidos (ADR-017):
- **E-mail**: "mande as decisões para ana@empresa.com" prepara o e-mail e mostra o texto com
  **Enviar** e **Descartar**. Nada sai sem o clique, e só para endereços que você escreveu.
- **Documento**: gera o arquivo com botão de download. Formatos: PDF, Word, Excel (xlsx), CSV,
  HTML e Markdown. Ex.: "gere a ata em PDF", "uma planilha Excel com as tarefas e prazos",
  "exporte as decisões em CSV", "um dashboard em HTML com as falas por participante". No HTML,
  cada tabela com números vira um gráfico de barras; os números (falas, tarefas, decisões) são
  contados pelo sistema, não pelo modelo.

## Agenda do Google (opcional)

1. No [Google Cloud Console](https://console.cloud.google.com): ative a **Google Calendar API** e crie
   uma credencial **OAuth → App para computador**. Baixe o JSON e salve em
   `data/google/credentials.json` (a pasta `data/` não vai para o git nem para a imagem).
2. No computador, uma vez: `python -m infrastructure.calendar.calendar_setup`. Abre o navegador para
   autorizar a leitura da agenda e grava `data/google/token.json`.
3. `ENABLE_CALENDAR=true` no `.env` e `docker compose up -d`.

Na tela **Enviar bot** aparecem as próximas reuniões da agenda (Meet, Zoom ou Teams) com o botão
**Mandar**, e o bot enviado por link recebe o título do evento. É uma agenda por instalação.

## Memória entre reuniões

O chat considera as decisões e tarefas abertas das suas outras reuniões ligadas à pergunta
("o que mudou desde a reunião anterior?") e diz de qual reunião veio cada item. Peça também
"lembre que prefiro atas em tópicos": a nota vale em todas as suas conversas e fica em
**Minha conta → Memória do agente**, onde dá para apagar (ADR-020).

## Observabilidade

Para o admin: página **Observabilidade** da interface, o **Diagnóstico** de cada reunião em Gravações e a API `/observability` (`summary`,
`metrics` no formato Prometheus, `logs` com filtros, `meetings/{id}` com a linha do tempo de uma
reunião em todos os serviços). Detalhes na ADR-019.

## Operação

Servidor com HTTPS: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`
(exige `DOMAIN` no `.env`). Roteiro completo — restaurar, trocar a chave, reiniciar o bot, alerta
— em [docs/operacao.md](docs/operacao.md); checklist antes de abrir para usuários em
[docs/seguranca.md](docs/seguranca.md).


- **Logs:** toda linha traz o id da reunião. `docker compose logs worker-transcribe worker-llm | grep <id>`
  segue uma reunião.
- **Backup:** `docker compose run --rm backup` gera `backups/mongo-<data>.archive.gz` e apaga
  gravações com mais de 30 dias (`AUDIO_RETENTION_DAYS`). Restaurar:
  `docker compose run --rm backup restore backups/<arquivo>`. Roda num container, então é o mesmo
  comando no Windows; `scripts/backup.sh` é só um atalho para ele.
- **Reunião com erro:** a mensagem aparece na interface; o botão "Reprocessar áudio gravado" refaz
  a transcrição e o resumo sem precisar de nova reunião.
- **Teste de fumaça do bot:** `python -m infrastructure.recorder.run_bot --url <link> --smoke 30`
  (com a API no ar e alguém para admitir o bot). Uma linha `FALHA` em legendas, presentes ou bloco
  do bot indica que o Meet mudou a tela.
- **Diagnóstico de nomes:** `data/audio/<id>.speakers.jsonl` mostra se as legendas ligaram
  (`captions`), quem estava (`participants`) e quem falou (`speaker`).

## Limites conhecidos

- O bot enxerga o **nome de exibição** de cada participante, não o e-mail.
- Trechos em que o Meet não gerou legenda ficam como "Speaker N" (com uma única pessoa além do
  bot, todas as falas são atribuídas a ela).
- As plataformas mudam a tela sem aviso; os seletores ficam em `infrastructure/recorder/`
  (`playwright_bot_recorder.py` para o Meet, `platforms.py` para as demais).
- Reuniões longas são resumidas em partes e o chat consulta só os trechos ligados à pergunta
  (ADR-010). `LLM_CONTEXT_CHARS` ajusta o tamanho de cada parte.
- Cada worker do bot grava uma reunião por vez (um perfil do Chrome por worker).
- Limite de 30 envios, bots e perguntas por usuário por minuto (`RATE_LIMIT_PER_MINUTE`).
- Login: 5 senhas erradas bloqueiam por 15 minutos; não há confirmação de e-mail no cadastro.
  A recuperação de senha exige SMTP configurado.
- Dois usuários que mandam o bot ao mesmo link compartilham uma gravação; cada um recebe a
  própria reunião quando ela termina.

## Testes e dependências

```bash
python -m pytest              # o teste com reunião real só roda com MEET_TEST_URL exportada
python -m scripts.eval_agent  # avalia o agente contra o contrato com o LLM de verdade (minutos)
```

Rode a avaliação depois de mudar o contrato, os prompts ou o modelo: ela não pode piorar.

As versões exatas ficam em `requirements.txt` e `requirements-dev.txt`, geradas a partir dos `.in`
em Python 3.11. Para atualizar:

```bash
docker run --rm -v "$PWD":/w -w /w python:3.11-slim sh -c \
  "pip install pip-tools && pip-compile --strip-extras -o requirements.txt requirements.in \
   && pip-compile --strip-extras -o requirements-dev.txt requirements-dev.in"
```

`requirements-diarization.in` lista as dependências da diarização por pyannote (opcional, não travadas).
