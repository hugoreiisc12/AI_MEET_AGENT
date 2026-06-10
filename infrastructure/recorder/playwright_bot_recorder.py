"""
playwright_bot_recorder.py — Bot Playwright corrigido.

Correções aplicadas:
  S1 — Login: launch_persistent_context() com perfil Chrome salvo pelo
       bot_setup.py + _verify_logged_in() como sanity check.
  S2 — Áudio: injeção do audio_capture.js (intercepta <audio> do Meet)
       em vez de getUserMedia (microfone local).
  S3 — Entrega: callback on_audio_ready injetado pelo use case.
  S4 — Fim de reunião: 3 sinais combinados (tela de saída, sozinho na
       sala, silêncio prolongado).
  S6 — Etapas documentadas pelos próprios session.status.
  S7 — Log temporal de voz/speaker salvo como JSON ao lado do .webm.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Optional

from playwright.async_api import BrowserContext, Page, async_playwright

logger = logging.getLogger(__name__)

AUDIO_CAPTURE_JS = (Path(__file__).parent / "audio_capture.js").read_text(
    encoding="utf-8"
)

OnAudioReady = Callable[[Path, Path], Awaitable[None]]


class BotNotLoggedInError(RuntimeError):
    """Sessão Google expirada/inexistente — rodar bot_setup.py novamente."""


@dataclass
class BotSession:
    meeting_url: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = "created"
    error: Optional[str] = None
    audio_path: Optional[Path] = None
    speaker_log_path: Optional[Path] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "meeting_url": self.meeting_url,
            "status": self.status,
            "error": self.error,
            "audio_path": str(self.audio_path) if self.audio_path else None,
            "speaker_log_path": (
                str(self.speaker_log_path) if self.speaker_log_path else None
            ),
        }


class PlaywrightBotRecorder:
    """Bot que entra no Google Meet, grava áudio da reunião e entrega
    o resultado via callback."""

    ALONE_TIMEOUT = 60
    SILENCE_TIMEOUT = 300
    POLL_INTERVAL = 5
    JOIN_TIMEOUT = 120_000

    def __init__(
        self,
        chrome_profile_dir: str | Path,
        audio_dir: str | Path,
        bot_name: str = "Meet Agent",
        headless: bool = False,
        status_dir: str | Path | None = None,
        on_audio_ready: OnAudioReady | None = None,
    ) -> None:
        self.chrome_profile_dir = Path(chrome_profile_dir)
        self.audio_dir = Path(audio_dir)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.bot_name = bot_name
        self.headless = headless
        self.status_dir = Path(status_dir) if status_dir else self.audio_dir
        self.on_audio_ready = on_audio_ready
        self.session: Optional[BotSession] = None

    async def join_async(self, meeting_url: str) -> BotSession:
        self.session = BotSession(meeting_url=meeting_url)
        self._persist_status()
        try:
            await self._run_session()
        except Exception as exc:
            logger.exception("Sessão do bot falhou")
            self._set_status("failed", error=f"{type(exc).__name__}: {exc}")
            raise
        return self.session

    async def _run_session(self) -> None:
        assert self.session is not None
        async with async_playwright() as pw:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(self.chrome_profile_dir),
                headless=self.headless,
                permissions=["microphone", "camera"],
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--use-fake-ui-for-media-stream",
                ],
            )
            try:
                page = context.pages[0] if context.pages else await context.new_page()

                self._set_status("logging_in")
                await self._verify_logged_in(page)

                self._set_status("joining")
                await page.goto(
                    self.session.meeting_url, wait_until="domcontentloaded"
                )
                await self._verify_logged_in(page)
                await self._prepare_devices(page)
                await self._click_join_button(page)
                await self._wait_admitted(page)

                self._set_status("recording")
                await self._inject_audio_capture(page)
                await self._wait_until_meeting_ends(page)

                self._set_status("saving")
                await self._collect_and_save_audio(page)

                self._set_status("delivering")
                await self._deliver()

                self._set_status("done")
            finally:
                await context.close()

    async def _verify_logged_in(self, page: Page) -> None:
        url = page.url or ""
        if "accounts.google.com" in url:
            raise BotNotLoggedInError(
                "Sessão Google expirada ou inexistente no perfil "
                f"'{self.chrome_profile_dir}'. Rode novamente: "
                "python infrastructure/recorder/bot_setup.py"
            )
        login_btn = page.locator(
            'a:has-text("Fazer login"), a:has-text("Sign in")'
        )
        if await login_btn.count() > 0 and await login_btn.first.is_visible():
            raise BotNotLoggedInError(
                "Página do Meet exibindo 'Fazer login' — sessão inválida. "
                "Rode novamente o bot_setup.py."
            )

    async def _prepare_devices(self, page: Page) -> None:
        for label_part in ("microfone", "microphone", "câmera", "camera"):
            try:
                btn = page.locator(
                    f'[aria-label*="Desativar"][aria-label*="{label_part}" i], '
                    f'[aria-label*="Turn off"][aria-label*="{label_part}" i]'
                )
                if await btn.count() > 0:
                    await btn.first.click(timeout=3000)
            except Exception:
                pass

    async def _click_join_button(self, page: Page) -> None:
        join = page.locator(
            'button:has-text("Participar agora"), '
            'button:has-text("Pedir para participar"), '
            'button:has-text("Join now"), '
            'button:has-text("Ask to join")'
        )
        await join.first.click(timeout=30_000)

    async def _wait_admitted(self, page: Page) -> None:
        in_call = page.locator(
            '[aria-label*="Sair da chamada" i], [aria-label*="Leave call" i]'
        )
        await in_call.first.wait_for(state="visible", timeout=self.JOIN_TIMEOUT)

    async def _inject_audio_capture(self, page: Page) -> None:
        await page.evaluate(AUDIO_CAPTURE_JS)
        await page.evaluate("window.__meetCapture._resume()")
        state = await page.evaluate("window.__meetCapture.getState()")
        logger.info("Captura iniciada: %s", state)
        if not state.get("recording"):
            raise RuntimeError(f"MediaRecorder não iniciou: {state}")

    async def _get_participant_count(self, page: Page) -> int:
        btn = page.locator(
            'button[aria-label*="articipante" i], '
            'button[aria-label*="essoas" i], '
            'button[aria-label*="people" i]'
        )
        try:
            if await btn.count() > 0:
                label = await btn.first.get_attribute("aria-label") or ""
                m = re.search(r"\d+", label)
                if m:
                    return int(m.group())
        except Exception:
            pass
        return -1

    async def _ended_screen_visible(self, page: Page) -> bool:
        ended = page.locator(
            "text=/saiu da chamada|chamada (foi )?encerrada|"
            "reunião encerrada|left the call|call ended/i"
        )
        try:
            return await ended.count() > 0 and await ended.first.is_visible()
        except Exception:
            return False

    async def _wait_until_meeting_ends(self, page: Page) -> None:
        alone_since: Optional[float] = None
        while True:
            await asyncio.sleep(self.POLL_INTERVAL)

            if await self._ended_screen_visible(page):
                logger.info("Fim detectado: tela de encerramento")
                return

            count = await self._get_participant_count(page)
            if count == 1:
                alone_since = alone_since or time.monotonic()
                if time.monotonic() - alone_since >= self.ALONE_TIMEOUT:
                    logger.info("Fim detectado: sozinho há %ss", self.ALONE_TIMEOUT)
                    return
            else:
                alone_since = None

            try:
                last_audio_ms = await page.evaluate(
                    "window.__meetCapture.getLastAudioTs()"
                )
                silence = time.time() - (last_audio_ms / 1000)
                if silence >= self.SILENCE_TIMEOUT:
                    logger.info("Fim detectado: %.0fs de silêncio", silence)
                    return
            except Exception:
                logger.info("Fim detectado: contexto de captura perdido")
                return

    async def _collect_and_save_audio(self, page: Page) -> None:
        assert self.session is not None
        b64: str = await page.evaluate("window.__meetCapture.stop()")
        audio_path = self.audio_dir / f"{self.session.id}.webm"
        audio_path.write_bytes(base64.b64decode(b64))

        speaker_log = await page.evaluate("window.__meetCapture.getSpeakerLog()")
        log_path = self.audio_dir / f"{self.session.id}.speakers.json"
        log_path.write_text(
            json.dumps(speaker_log, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self.session.audio_path = audio_path
        self.session.speaker_log_path = log_path
        logger.info(
            "Áudio salvo: %s (%.1f KB) | speaker log: %s eventos",
            audio_path, audio_path.stat().st_size / 1024, len(speaker_log),
        )

    async def _deliver(self) -> None:
        assert self.session is not None
        if self.on_audio_ready and self.session.audio_path:
            await self.on_audio_ready(
                self.session.audio_path, self.session.speaker_log_path
            )

    def _set_status(self, status: str, error: str | None = None) -> None:
        assert self.session is not None
        self.session.status = status
        self.session.error = error
        logger.info("status=%s%s", status, f" error={error}" if error else "")
        self._persist_status()

    def _persist_status(self) -> None:
        assert self.session is not None
        path = self.status_dir / f"bot_session_{self.session.id}.json"
        path.write_text(
            json.dumps(self.session.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
