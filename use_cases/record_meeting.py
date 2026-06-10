"""
use_cases/record_meeting.py

Orquestra o bot de reunião — entra, aguarda, retorna áudio.

Suporta dois modos:
  - Direto: recorder.join_async() em background thread
  - Processo separado: via subprocess (S5), polling de status JSON
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
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
        self._processes: dict[str, subprocess.Popen] = {}

    def send_bot(self, input_data: SendBotInput) -> SendBotOutput:
        import uuid
        meeting_id = input_data.meeting_id or str(uuid.uuid4())
        session_id = meeting_id[:8]

        try:
            session = self._recorder.join_async(input_data.meeting_url)
            if hasattr(session, 'id'):
                session_id = session.id[:8]
            else:
                session_id = meeting_id[:8]
            self._sessions[session_id] = session

            on_finished = input_data.on_finished
            if on_finished:
                def _watch():
                    import asyncio
                    if hasattr(session, 'audio_path'):
                        if session.status == "done" and not session.error:
                            on_finished(
                                str(session.audio_path),
                                input_data.title,
                                getattr(session, 'participant_info', {}),
                                getattr(session, 'speaker_observations', []),
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

    def launch_bot_subprocess(self, meeting_url: str, audio_dir: str) -> str:
        """S5 — Lança o bot em processo separado via run_bot.py."""
        import uuid
        session_id = uuid.uuid4().hex[:12]

        proc = subprocess.Popen(
            [sys.executable, "-m", "infrastructure.recorder.run_bot",
             "--url", meeting_url, "--audio-dir", audio_dir],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._processes[session_id] = proc
        return session_id

    def get_status(self, session_id: str) -> BotStatusOutput:
        session = self._sessions.get(session_id)
        if session:
            return BotStatusOutput(
                session_id=session_id,
                status=getattr(session, "status", "unknown"),
                duration_seconds=0.0,
                audio_path=str(session.audio_path) if getattr(session, "audio_path", None) else "",
                error_message=getattr(session, "error", "") or "",
            )
        return BotStatusOutput(session_id=session_id, status="not_found")

    def list_active_sessions(self) -> list[BotStatusOutput]:
        return [
            self.get_status(sid)
            for sid, s in self._sessions.items()
            if getattr(s, "status", "") in ("joining", "recording", "logging_in")
        ]