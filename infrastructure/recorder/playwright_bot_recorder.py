"""Playwright-based recorder bot.

Este módulo contém a implementação do `PlaywrightBotRecorder` usada para
entrar em chamadas do Google Meet e coletar áudio localmente.
"""

from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class BotSession:
    meeting_url: str
    output_path: Optional[Path] = None
    status: str = "idle"
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_message: str = ""
    audio_chunks: list[str] = field(default_factory=list, repr=False)

    @property
    def duration_seconds(self) -> float:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return 0.0


class PlaywrightBotRecorder:
    _SEL_JOIN_BTN = [
        '[data-promo-anchor-id="join-button"]',
        'button[jsname="Qx7uuf"]',
        'button:has-text("Participar agora")',
    ]

    _SEL_MIC_BTN = [
        '[aria-label*="desativar microfone"]',
        '[aria-label*="Mute microphone"]',
    ]

    def __init__(self, google_email: str, google_password: str, profile_dir: str = "./bot_chrome_profile", bot_name: str = "Meet Agent 🤖", output_dir: str = "data/audio", headless: bool = False) -> None:
        self._email = google_email
        self._password = google_password
        self._profile_dir = Path(profile_dir)
        self._bot_name = bot_name
        self._output_dir = Path(output_dir)
        self._headless = headless

        self._profile_dir.mkdir(parents=True, exist_ok=True)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def join_async(self, meeting_url: str):
        output_path = self._output_dir / f"bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        session = BotSession(meeting_url=meeting_url, output_path=output_path)

        def _run():
            try:
                asyncio.run(self._run_session(session))
            except Exception:
                session.status = "error"
                session.error_message = "internal error"

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return session, thread

    async def _run_session(self, session: BotSession) -> None:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(user_data_dir=str(self._profile_dir), headless=self._headless, args=["--use-fake-ui-for-media-stream"]) 
            page = await context.new_page()
            await page.goto(session.meeting_url, wait_until="networkidle")
            # Simplified: inject recording and wait
            await self._inject_audio_capture(page)
            await asyncio.sleep(5)
            await context.close()

    async def _inject_audio_capture(self, page) -> None:
        await page.evaluate("""
            window.__audioChunks = [];
            async function startAudioCapture(){
                try{
                    const stream = await navigator.mediaDevices.getUserMedia({audio:true});
                    const mr = new MediaRecorder(stream, {mimeType:'audio/webm;codecs=opus'});
                    mr.ondataavailable = (e)=>{ if(e.data.size) { const r=new FileReader(); r.onloadend=()=>window.__audioChunks.push(r.result); r.readAsDataURL(e.data); }};
                    mr.start(5000);
                }catch(e){console.error(e)}
            }
            startAudioCapture();
        """)
