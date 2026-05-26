"""
Orquestra o bot de reunião — entra, aguarda, retorna áudio.
Não sabe se é Playwright, Recall.ai ou outro — recebe via injeção.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional, Callable


# entrada para enviar o bot para reunião ( sem bloqueio, receber o fallback on_finished)
@dataclass
class SendBotInput:
    meeting_url: str
    title: str = "Reunião"
    on_finished: Optional[Callable[[str, str], None]] = None
    # on_finished(audio_path, title) — chamado quando reunião terminar


# saida função send_bot() imediatamente, o audio é processado
@dataclass
class SendBotOutput:
    session_id: str          # ID único da sessão (para acompanhar status)
    success: bool
    error_message: str = ""

# Status atual do bot para uma reunião especifica 
@dataclass
class BotStatusOutput:
    session_id: str
    status: str              # idle, logging_in, joining, recording, done, error
    duration_seconds: float = 0.0
    audio_path: str = ""
    error_message: str = ""


# use case principal para gerenciar o ciclo de vida do bot na reunião
class RecordMeetingUC:
    """
    Use case: envia o bot para a reunião e gerencia o ciclo de vida.

    Em modo solo: roda em thread separada, não bloqueia o Streamlit.
    Em modo collab: pode ser delegado para um worker Celery.
    """

# Injeção do recorder (Playwrigtht, Recall.ai, etc) para não acoplar a implementação do bot 
    def __init__(self, recorder) -> None:
        self._recorder = recorder
        self._sessions: dict = {}   # session_id → BotSession

    def send_bot(self, input_data: SendBotInput) -> SendBotOutput:
        """
        Envia o bot para a reunião de forma não-bloqueante.
        O bot grava em background — use get_status() para acompanhar.
        """
        import uuid
        session_id = str(uuid.uuid4())[:8]

        try:
            session, thread = self._recorder.join_async(input_data.meeting_url)
            self._sessions[session_id] = session

            # Quando terminar, dispara callback se fornecido
            if input_data.on_finished:
                def _watch():
                    thread.join()
                    if session.status == "done":
                        input_data.on_finished(session.output_path, input_data.title)

                threading.Thread(target=_watch, daemon=True).start()

            return SendBotOutput(session_id=session_id, success=True)

        except Exception as e:
            return SendBotOutput(
                session_id=session_id,
                success=False,
                error_message=str(e),
            )

    def get_status(self, session_id: str) -> BotStatusOutput:
        """Retorna o status atual de uma sessão do bot."""
        session = self._sessions.get(session_id)

        if not session:
            return BotStatusOutput(
                session_id=session_id,
                status="not_found",
            )

        return BotStatusOutput(
            session_id=session_id,
            status=session.status,
            duration_seconds=session.duration_seconds,
            audio_path=session.output_path if session.status == "done" else "",
            error_message=session.error_message,
        )

    def list_active_sessions(self) -> list[BotStatusOutput]:
        """Retorna todas as sessões ativas."""
        return [
            self.get_status(sid)
            for sid, s in self._sessions.items()
            if s.status in ("joining", "recording", "logging_in")
        ]