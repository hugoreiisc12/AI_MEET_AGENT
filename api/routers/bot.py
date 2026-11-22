"""Credenciamento da conta do Google do bot pela interface (sem rodar bot_setup no terminal)."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.security import Principal, current_principal
from presentation.container import get_container

router = APIRouter()


class BotStatusResponse(BaseModel):
    status: Literal["unknown", "creating", "waiting_login", "ready", "not_configured", "error", "offline"] = Field(
        description="ready libera o envio do bot. creating: credenciando. waiting_login: alguém precisa "
                    "concluir o login na tela do bot (vnc_url). unknown/not_configured/error: credenciar. "
                    "offline: conta pronta, mas nenhum worker do bot rodando (message diz como subir).")
    message: str = ""
    vnc_url: str = Field("", description="Tela do navegador do bot (noVNC), para concluir o login")


@router.get("/status", response_model=BotStatusResponse, summary="O bot está credenciado?")
def bot_status(principal: Principal = Depends(current_principal)):
    """Consultar a cada poucos segundos enquanto status for creating ou waiting_login."""
    return get_container().bot_status()


@router.post("/setup", response_model=BotStatusResponse, status_code=202, summary="Credencia o bot",
             responses={403: {"description": "Só o administrador credencia o bot"},
                        409: {"description": "Sem fila do bot (modo solo)"}})
def setup_bot(principal: Principal = Depends(current_principal)):
    """Abre o navegador do bot e conecta a conta do Google: sozinho com BOT_GOOGLE_EMAIL e
    BOT_GOOGLE_PASSWORD no .env, ou pedindo para alguém concluir na tela do bot (vnc_url)
    quando não há senha configurada ou o Google pede verificação. Acompanhe por GET /bot/status."""
    if principal.user is not None and not principal.user.is_admin:
        raise HTTPException(403, "Só o administrador credencia o bot")
    container = get_container()
    if container.bot_account is None:
        raise HTTPException(409, "Credenciamento só existe no modo collab (bot na fila)")
    return container.request_bot_setup()
