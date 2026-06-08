"""
use_cases/record_meeting.py

Orquestra o bot de reunião — entra, aguarda, retorna áudio.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional, Callable


@dataclass
class SendBotInput:
    meeting_url: str
    title: str = "Reunião"
    meeting_id: Optional[str] = None
    on_finished: Optional[Callable[[str, str, dict[str, str], list[dict[str, float | str]], str], None]] = None


@dataclass
class SendBotOutput:
    session_id: str
    success: bool
    error_message: str = ""


@dataclass
class BotStatusOutput:
    session_id: str
    status: str
    duration_seconds: float = 0.0
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
        meeting_id = input_data.meeting_id or str(uuid.uuid4())
        session_id = meeting_id[:8]

        try:
            session, thread = self._recorder.join_async(input_data.meeting_url)
            self._sessions[session_id] = session

            on_finished = input_data.on_finished
            if on_finished:
                def _watch():
                    thread.join()
                    if session.status == "done" and not session.error_message:
                        on_finished(
                            str(session.output_path),
                            input_data.title,
                            session.participant_info,
                            session.speaker_observations,
                            meeting_id,
                        )
                threading.Thread(target=_watch, daemon=True).start()

            return SendBotOutput(session_id=session_id, success=True)

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
            duration_seconds=getattr(session, "duration_seconds", 0.0),
            audio_path=str(session.output_path) if session.status == "done" else "",
            error_message=session.error_message,
        )

    def list_active_sessions(self) -> list[BotStatusOutput]:
        return [
            self.get_status(sid)
            for sid, s in self._sessions.items()
            if s.status in ("joining", "recording", "logging_in")
        ]