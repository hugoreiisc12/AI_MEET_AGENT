"""api/main.py — FastAPI. A especificação da API está em /docs (Swagger) e em
docs/api/openapi.json (gerada por `python -m api.export_openapi`)."""
import logging
from fastapi import Depends, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from api import chat
from api.routers import auth, bot, calendar, capture, meetings, memory, observability
from api.routers.meetings import AUDIO_SUFFIXES
from api.schemas.meeting import ConfigResponse, PlatformSchema
from api.security import current_principal
from config.logging_setup import setup_logging
from config.settings import get_settings
from infrastructure.recorder.platforms import PLATFORMS
from presentation.container import get_container

setup_logging()
settings = get_settings()

DESCRIPTION = """
API do Meet Agent: o bot entra na reunião, grava, transcreve, resume e responde perguntas.

## Autenticação

1. `POST /auth/register` ou `POST /auth/login` devolve um `token`.
2. Envie `Authorization: Bearer <token>` nas rotas de **meetings** e **chat**.
3. Cada usuário enxerga só as próprias reuniões; a reunião de outro usuário responde 404.
4. Cinco senhas erradas seguidas bloqueiam o login por 15 minutos (429).

Se dois usuários mandam o bot ao mesmo link, um só bot grava e cada um recebe a própria
reunião, com chat e tarefas independentes.

Integrações sem usuário podem usar a chave de serviço no cabeçalho `X-API-Key`.

## Fluxo de uma reunião

1. `POST /meetings/bot` (link) ou `POST /meetings/upload` (áudio) devolve o `meeting_id`.
2. Consulte `GET /meetings/{id}/status` a cada 5 s: `pending` → `recording` →
   `transcribing` → `summarizing` → `done` (ou `error`, com o motivo em `error`).
3. Com `done`, `GET /meetings/{id}` traz resumo, tarefas, transcrição e conversa.
4. `POST /meetings/{id}/chat` responde perguntas sobre a reunião.

## Erros

Toda resposta de erro tem o formato `{"detail": "mensagem"}` (ou a lista de validação do
FastAPI em 422). `401` = credencial ausente, inválida ou sessão expirada: refaça o login.
"""

TAGS = [
    {"name": "auth", "description": "Cadastro, login e sessão do usuário."},
    {"name": "meetings", "description": "Reuniões: criar (bot ou upload), acompanhar, ler, apagar."},
    {"name": "chat", "description": "Perguntas sobre uma reunião já transcrita."},
    {"name": "admin", "description": "Só para administradores (a primeira conta): usuários e limpeza de sessões."},
    {"name": "sistema", "description": "Configuração para o front e verificação de saúde. Sem autenticação."},
    {"name": "agenda", "description": "Próximas reuniões do Google Calendar (ENABLE_CALENDAR), com o link para mandar o bot."},
    {"name": "memória", "description": "Notas que o usuário pediu para o agente lembrar entre reuniões (§14 do contrato)."},
    {"name": "observabilidade", "description": "Métricas (JSON e Prometheus), logs centralizados de todos os serviços e linha do tempo por reunião. Só administrador."},
    {"name": "bot", "description": "Credenciamento da conta do Google do bot: o envio do bot só é liberado com status ready."},
    {"name": "capture", "description": "Uso interno do bot (áudio em chunks). O front não chama."},
]

app = FastAPI(title="Meet Agent API", version="2.0.0", description=DESCRIPTION, openapi_tags=TAGS)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SLOW_REQUEST_S = 5.0


@app.middleware("http")
async def _http_metrics(request, call_next):
    """Contagem e duração por rota (o molde, ex. /meetings/{meeting_id}, não o id) e status."""
    import time
    from infrastructure import observability as obs
    t0 = time.monotonic()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        path = getattr(route, "path", "outro")
        labels = {"method": request.method, "route": path}
        elapsed = time.monotonic() - t0
        obs.observe("http_request_seconds", elapsed, labels)
        obs.incr("http_requests_total", {**labels, "status": str(status)})
        # No log central só o que pede atenção: erro do servidor ou pedido lento.
        if status >= 500 or elapsed > SLOW_REQUEST_S:
            logging.getLogger("api.http").warning("%s %s → %s em %.1fs", request.method, path, status, elapsed)


_auth = [Depends(current_principal)]
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(auth.admin_router, prefix="/admin", tags=["admin"])
app.include_router(meetings.router, prefix="/meetings", tags=["meetings"], dependencies=_auth)
app.include_router(chat.router, prefix="/meetings", tags=["chat"], dependencies=_auth)
# /capture/* tem autenticação própria: token por sessão (api/security.py).
app.include_router(capture.router, prefix="/capture", tags=["capture"])
app.include_router(bot.router, prefix="/bot", tags=["bot"], dependencies=_auth)
app.include_router(calendar.router, prefix="/calendar", tags=["agenda"], dependencies=_auth)
app.include_router(memory.router, prefix="/memory", tags=["memória"], dependencies=_auth)
app.include_router(observability.router, prefix="/observability", tags=["observabilidade"], dependencies=_auth)


@app.get("/config", response_model=ConfigResponse, tags=["sistema"], summary="O que está ligado nesta instalação")
def config():
    """O front lê uma vez na partida para montar as telas (cadastro aberto? e-mail ligado? quais plataformas?)."""
    s = get_settings()
    return ConfigResponse(
        mode=s.app_mode.value,
        login_enabled=True,
        registration_open=s.allow_registration,
        email_enabled=s.email_enabled,
        calendar_enabled=s.enable_calendar,
        max_upload_mb=s.max_upload_mb,
        audio_formats=sorted(AUDIO_SUFFIXES),
        platforms=[
            PlatformSchema(key=p.key, label=p.label, example=p.example,
                           validated=p.validated, speaker_names=p.speaker_names)
            for p in PLATFORMS if not p.unsupported
        ],
    )


def _workers() -> dict:
    """Workers vivos por fila, pelo batimento que cada um grava no Redis (ADR-015). Sem worker em
    `transcribe` ou `llm`, as reuniões ficam paradas na fila sem erro nenhum: é isso que o alerta
    da S11-4 precisa ver. O bot é informativo: pode rodar no host e nem sempre está ligado."""
    from infrastructure import observability as obs
    alive = obs.workers()
    if alive is None:
        return {"workers": "erro: sem leitura do Redis"}
    return {f"worker_{q}" if q != "bot" else "bot": "ok" if alive.get(q) else "sem worker"
            for q in ("transcribe", "llm", "bot")}


@app.get("/health", tags=["sistema"], summary="Saúde do banco, da fila e dos workers")
def health(response: Response):
    """Confere as dependências de verdade: 503 se o banco ou a fila não respondem, ou se
    uma etapa (`worker_transcribe`, `worker_llm`) está sem worker. `bot` só informa."""
    checks = {}
    try:
        get_container().repository.find_by_id("__health__")
        checks["storage"] = "ok"
    except Exception as exc:
        checks["storage"] = f"erro: {type(exc).__name__}"
    if settings.is_collab:
        try:
            import redis
            redis.Redis.from_url(settings.redis_url, socket_timeout=2, socket_connect_timeout=2).ping()
            checks["queue"] = "ok"
        except Exception as exc:
            checks["queue"] = f"erro: {type(exc).__name__}"
        if checks["queue"] == "ok":
            checks.update(_workers())
    ok = all(v == "ok" for k, v in checks.items() if k != "bot")
    if not ok:
        response.status_code = 503
    return {"status": "ok" if ok else "degraded", "mode": settings.app_mode, **checks}
