"""
use_cases/record_meeting.py

Orquestra o bot de reunião — entra, aguarda, retorna áudio.
Adaptado para PlaywrightBotRecorder (S1-S7) com BotSession atualizada.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional, Callable


@dataclass
class SendBotInput:
    meeting_url: str
    title: str = "Reunião"
    on_finished: Optional[Callable[[str, str], None]] = None


@dataclass
class SendBotOutput:
    session_id: str
    success: bool
    error_message: str = ""


@dataclass
class BotStatusOutput:
    session_id: str
    status: str
    audio_path: str = ""
    error_message: str = ""


class RecordMeetingUC:
    """
    Use case: envia o bot para a reunião e gerencia o ciclo de vida.
    Não sabe se é Playwright ou outro recorder — recebe via injeção.
    """

    def __init__(self, recorder) -> None:
        self._recorder = recorder
        self._sessions: dict = {}

    def send_bot(self, input_data: SendBotInput) -> SendBotOutput:
        import uuid
        import asyncio
        session_id = str(uuid.uuid4())[:8]

        try:
            # join_async é async — roda em event loop próprio
            loop = asyncio.new_event_loop()
            session = loop.run_until_complete(
                self._recorder.join_async(input_data.meeting_url)
            )
            loop.close()
            self._sessions[session_id] = session

            on_finished = input_data.on_finished
            if on_finished:
                def _watch():
                    # Aguarda o status ser 'done' via polling do JSON
                    import time
                    from pathlib import Path
                    status_path = Path(session.audio_path).parent / f"bot_session_{session.id}.json"
                    while True:
                        time.sleep(2)
                        if status_path.exists():
                            data = __import__("json").loads(status_path.read_text(encoding="utf-8"))
                            if data.get("status") in ("done", "failed"):
                                if data["status"] == "done" and session.audio_path:
                                    on_finished(str(session.audio_path), input_data.title)
                                break

                threading.Thread(target=_watch, daemon=True).start()

            return SendBotOutput(session_id=session.id, success=True)

        except Exception as e:
            return SendBotOutput(
                session_id=session_id,
                success=False,
                error_message=str(e),
            )

    def get_status(self, session_id: str) -> BotStatusOutput:
        session = self._sessions.get(session_id)
        if not session:
            return BotStatusOutput(session_id=session_id, status="not_found")

        return BotStatusOutput(
            session_id=session_id,
            status=session.status,
            audio_path=str(session.audio_path) if session.status == "done" else "",
            error_message=session.error or "",
        )

    def list_active_sessions(self) -> list[BotStatusOutput]:
        return [
            self.get_status(sid)
            for sid, s in self._sessions.items()
            if s.status in ("joining", "recording", "logging_in")
        ]
