"""Cadastro, login, sessões e senha (ADR-011)."""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.security import Principal, current_user
from presentation.container import get_container
from use_cases.auth import MIN_PASSWORD, AccountLocked, AuthError, session_id

router = APIRouter()
admin_router = APIRouter()


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120, examples=["Maria Souza"])
    email: str = Field(max_length=254, examples=["maria@empresa.com"])
    password: str = Field(min_length=MIN_PASSWORD, max_length=200)


class LoginRequest(BaseModel):
    email: str = Field(max_length=254, examples=["maria@empresa.com"])
    password: str = Field(max_length=200)


class UserSchema(BaseModel):
    id: str
    name: str
    email: str
    created_at: datetime
    role: Literal["user", "admin"] = "user"


class SessionResponse(BaseModel):
    token: str = Field(description="Enviar em `Authorization: Bearer <token>` nas demais rotas.")
    user: UserSchema


class SessionSchema(BaseModel):
    id: str = Field(description="Identificador da sessão (não serve para entrar)")
    created_at: datetime
    expires_at: datetime
    user_agent: str = ""
    ip: str = ""
    current: bool = Field(description="É a sessão que fez esta chamada")


class CountResponse(BaseModel):
    count: int


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(min_length=MIN_PASSWORD, max_length=200)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(max_length=254)


class ResetPasswordRequest(BaseModel):
    email: str = Field(max_length=254)
    code: str = Field(min_length=1, max_length=20, description="Código recebido por e-mail")
    new_password: str = Field(min_length=MIN_PASSWORD, max_length=200)


class PurgeSessionsRequest(BaseModel):
    scope: Literal["expired", "user", "all_but_mine"] = Field(
        description="`expired`: vencidas · `user`: todas de `user_id` · `all_but_mine`: todas, menos a sua")
    user_id: str = Field("", description="Obrigatório quando scope = user")
    confirm: Literal["LIMPAR"] = Field(description="Digite LIMPAR para confirmar")


def _auth():
    auth = get_container().auth
    if auth is None:
        raise HTTPException(503, "Login indisponível neste modo (APP_MODE=solo não tem usuários)")
    return auth


def _user_schema(user) -> UserSchema:
    return UserSchema(id=user.id, name=user.name, email=user.email, created_at=user.created_at, role=user.role)


def _client(request: Request) -> tuple[str, str]:
    return request.headers.get("user-agent", ""), request.client.host if request.client else ""


# ── Conta e sessão ────────────────────────────────────────────────────

@router.post("/register", response_model=SessionResponse, status_code=201, summary="Cadastra um usuário",
             responses={409: {"description": "E-mail já cadastrado, dado inválido ou cadastro fechado"}})
def register(body: RegisterRequest, request: Request):
    """Cria a conta e já devolve uma sessão aberta. A primeira conta é administradora."""
    _auth()
    try:
        user = get_container().register_user(body.name, body.email, body.password)
    except AuthError as exc:
        raise HTTPException(409, str(exc))
    return SessionResponse(token=_auth().open_session(user, *_client(request)), user=_user_schema(user))


@router.post("/login", response_model=SessionResponse, summary="Abre uma sessão", responses={
    401: {"description": "E-mail ou senha incorretos"},
    429: {"description": "Conta bloqueada após 5 senhas erradas seguidas (15 min)"},
})
def login(body: LoginRequest, request: Request):
    try:
        token, user = _auth().login(body.email, body.password, *_client(request))
    except AccountLocked as exc:
        raise HTTPException(429, str(exc))
    except AuthError as exc:
        raise HTTPException(401, str(exc))
    return SessionResponse(token=token, user=_user_schema(user))


@router.post("/logout", status_code=204, summary="Encerra a sessão atual")
def logout(principal: Principal = Depends(current_user)):
    _auth().logout(principal.token)


@router.get("/me", response_model=UserSchema, summary="Usuário da sessão")
def me(principal: Principal = Depends(current_user)):
    return _user_schema(principal.user)


@router.get("/sessions", response_model=list[SessionSchema], summary="Minhas sessões ativas")
def my_sessions(principal: Principal = Depends(current_user)):
    current = session_id(principal.token)
    return [
        SessionSchema(id=s["_id"], created_at=s["created_at"], expires_at=s["expires_at"],
                      user_agent=s.get("user_agent", ""), ip=s.get("ip", ""), current=s["_id"] == current)
        for s in _auth().sessions(principal.user)
    ]


@router.delete("/sessions/{sid}", status_code=204, summary="Encerra uma das minhas sessões",
               responses={404: {"description": "Sessão não existe ou é de outro usuário"}})
def end_session(sid: str, principal: Principal = Depends(current_user)):
    try:
        _auth().end_session(principal.user, sid)
    except LookupError as exc:
        raise HTTPException(404, str(exc))


@router.delete("/sessions", response_model=CountResponse, summary="Encerra todas as minhas outras sessões")
def end_other_sessions(principal: Principal = Depends(current_user)):
    """A sessão que fez a chamada continua aberta."""
    return CountResponse(count=_auth().end_other_sessions(principal.user, principal.token))


# ── Senha ─────────────────────────────────────────────────────────────

@router.post("/password", response_model=CountResponse, summary="Troca a senha",
             responses={400: {"description": "Senha atual incorreta"}})
def change_password(body: ChangePasswordRequest, principal: Principal = Depends(current_user)):
    """Encerra as outras sessões do usuário; `count` diz quantas."""
    try:
        ended = _auth().change_password(principal.user, body.current_password, body.new_password, principal.token)
    except AuthError as exc:
        raise HTTPException(400, str(exc))
    return CountResponse(count=ended)


@router.post("/password/forgot", status_code=202, summary="Envia um código de nova senha por e-mail",
             responses={503: {"description": "E-mail (SMTP) não configurado"}})
def forgot_password(body: ForgotPasswordRequest):
    """Responde igual exista ou não a conta, para não revelar quem tem cadastro.
    O código vale 15 minutos e aceita 5 tentativas."""
    _auth()
    try:
        get_container().send_password_reset(body.email)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    return {"detail": "Se o e-mail tiver conta, o código foi enviado."}


@router.post("/password/reset", status_code=204, summary="Cria a nova senha com o código recebido",
             responses={400: {"description": "Código inválido, vencido ou com tentativas esgotadas"}})
def reset_password(body: ResetPasswordRequest):
    """Encerra todas as sessões da conta e desfaz um bloqueio por senhas erradas."""
    try:
        _auth().reset_password(body.email, body.code, body.new_password)
    except AuthError as exc:
        raise HTTPException(400, str(exc))


# ── Administração ─────────────────────────────────────────────────────

def _admin(principal: Principal = Depends(current_user)) -> Principal:
    if not principal.user.is_admin:
        raise HTTPException(403, "Apenas administradores")
    return principal


@admin_router.get("/users", response_model=list[UserSchema], summary="Lista os usuários")
def list_users(principal: Principal = Depends(_admin)):
    return [_user_schema(u) for u in _auth().users(principal.user)]


@admin_router.post("/sessions/purge", response_model=CountResponse, summary="Limpa sessões",
                   responses={400: {"description": "Usuário inexistente"}})
def purge_sessions(body: PurgeSessionsRequest, principal: Principal = Depends(_admin)):
    """Apaga só sessões: nunca usuários nem reuniões, e nunca a sessão de quem limpa.
    Quem teve a sessão apagada precisa entrar de novo."""
    try:
        count = _auth().purge_sessions(principal.user, body.scope, principal.token, body.user_id)
    except AuthError as exc:
        raise HTTPException(400, str(exc))
    return CountResponse(count=count)


# ── Modo de execução ──────────────────────────────────────────────────

class ModeRequest(BaseModel):
    mode: Literal["solo", "collab"]


class ModeResponse(BaseModel):
    mode: Literal["solo", "collab"]
    message: str


def _collab_unreachable(settings) -> str:
    """Mensagem de erro se o MongoDB ou o Redis do .env não respondem; vazio se ambos respondem."""
    try:
        from pymongo import MongoClient
        MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=2000).admin.command("ping")
    except Exception as exc:
        return f"MongoDB fora do ar ({settings.mongo_uri}): {str(exc).splitlines()[0][:160]}"
    try:
        import redis
        redis.Redis.from_url(settings.redis_url, socket_timeout=2).ping()
    except Exception as exc:
        return f"Redis fora do ar ({settings.redis_url}): {str(exc).splitlines()[0][:160]}"
    return ""


@admin_router.post("/mode", response_model=ModeResponse, summary="Alterna entre modo solo e colaborativo",
                   responses={409: {"description": "Configuração ou serviços do modo de destino indisponíveis"}})
def switch_mode(body: ModeRequest, principal: Principal = Depends(_admin)):
    """Troca o modo deste processo da API e remonta o container. Solo guarda reuniões e contas em
    arquivos; collab usa MongoDB, Redis e workers. As contas de um modo não valem no outro: depois
    da troca, entre com uma conta do modo novo (a primeira cadastrada vira administradora).
    ponytail: não persiste; ao reiniciar a API vale o APP_MODE do .env. Só com API_WORKERS=1,
    porque cada processo do uvicorn tem o próprio modo."""
    from config.settings import AppMode, Settings, get_settings
    from presentation import container as container_module

    settings = get_settings()
    target = AppMode(body.mode)
    if settings.app_mode == target:
        return ModeResponse(mode=target.value, message="A API já está nesse modo.")
    if settings.api_workers > 1:
        raise HTTPException(409, f"Com API_WORKERS={settings.api_workers} cada processo teria um modo. "
                                 "Troque o APP_MODE no .env e reinicie a API.")
    try:
        candidate = Settings(app_mode=target)
    except ValueError as exc:
        raise HTTPException(409, f"Não foi possível mudar para {target.value}: {exc}")
    if target == AppMode.COLLAB:
        error = _collab_unreachable(candidate)
        if error:
            raise HTTPException(409, f"Não foi possível mudar para collab: {error}")
    settings.app_mode = target
    container_module.get_container.cache_clear()
    return ModeResponse(mode=target.value, message=f"Modo {target.value} ativo. Entre com uma conta deste modo.")
