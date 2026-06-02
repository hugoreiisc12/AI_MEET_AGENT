"""Playwright-based recorder bot.

Este módulo contém a implementação do `PlaywrightBotRecorder` usada para
entrar em chamadas do Google Meet e coletar áudio localmente.

Fluxo:
    join_async()
        └─ _run_session()
             ├─ _click_join_button()       # entra na sala
             ├─ _inject_audio_capture()    # inicia gravação no browser
             ├─ _wait_until_meeting_ends() # aguarda fim real da reunião
             ├─ _collect_and_save_audio()  # lê chunks JS → salva .webm
             └─ session.status = "done"   # sinaliza para RecordMeetingUC
"""

from __future__ import annotations

import asyncio
import base64
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
    # Seletores do botão "Participar" — Google Meet muda o DOM com frequência,
    # então tentamos vários em ordem até um funcionar.
    _SEL_JOIN_BTN = [
        '[data-promo-anchor-id="join-button"]',
        'button[jsname="Qx7uuf"]',
        'button:has-text("Participar agora")',
        'button:has-text("Join now")',
    ]

    # Seletores que indicam que a reunião terminou (tela de saída do Meet)
    _SEL_MEETING_ENDED = [
        '[data-call-ended="true"]',
        'button:has-text("Voltar para a tela inicial")',
        'button:has-text("Return to home screen")',
        'h1:has-text("Você saiu da videochamada")',
        'h1:has-text("You left the video call")',
    ]

    # Timeout máximo de gravação: 4 horas (segurança contra reuniões infinitas)
    _MAX_RECORDING_SECONDS = 4 * 60 * 60

    # Intervalo de polling para detectar fim da reunião
    _POLL_INTERVAL_SECONDS = 10

    def __init__(
        self,
        google_email: str,
        google_password: str,
        profile_dir: str = "./bot_chrome_profile",
        bot_name: str = "Meet Agent 🤖",
        output_dir: str = "data/audio",
        headless: bool = False,
    ) -> None:
        self._email = google_email
        self._password = google_password
        self._profile_dir = Path(profile_dir)
        self._bot_name = bot_name
        self._output_dir = Path(output_dir)
        self._headless = headless

        self._profile_dir.mkdir(parents=True, exist_ok=True)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    # ── API pública ────────────────────────────────────────────────────────

    def join_async(self, meeting_url: str) -> tuple[BotSession, threading.Thread]:
        """Inicia o bot em background. Retorna (session, thread) imediatamente."""
        output_path = self._output_dir / f"bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.webm"
        session = BotSession(meeting_url=meeting_url, output_path=output_path)

        def _run() -> None:
            try:
                asyncio.run(self._run_session(session))
            except Exception as exc:
                session.status = "error"
                session.error_message = str(exc)
                session.finished_at = datetime.now()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return session, thread

    # ── Ciclo de vida da sessão ────────────────────────────────────────────

    async def _run_session(self, session: BotSession) -> None:
        from playwright.async_api import async_playwright

        session.status = "logging_in"
        session.started_at = datetime.now()

        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(self._profile_dir),
                headless=self._headless,
                args=[
                    "--use-fake-ui-for-media-stream",   # libera getUserMedia sem popup
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            page = await context.new_page()

            try:
                # 1. Navega para a reunião
                await page.goto(session.meeting_url, wait_until="networkidle", timeout=30_000)

                # 2. Entra na sala
                session.status = "joining"
                await self._click_join_button(page)

                # 3. Inicia captura de áudio no browser
                session.status = "recording"
                await self._inject_audio_capture(page)

                # 4. Aguarda a reunião terminar (ou timeout)
                await self._wait_until_meeting_ends(page)

                # 5. Coleta chunks gravados e salva em disco
                await self._collect_and_save_audio(page, session)

            finally:
                # Garante que o contexto sempre fecha, mesmo em erro
                await context.close()

        # 6. Marca sessão como concluída — _watch() em RecordMeetingUC detecta aqui
        session.status = "done"
        session.finished_at = datetime.now()

    # ── Entrar na reunião ──────────────────────────────────────────────────

    async def _click_join_button(self, page) -> None:
        """Tenta cada seletor do botão 'Participar' até um funcionar."""
        for selector in self._SEL_JOIN_BTN:
            try:
                await page.wait_for_selector(selector, timeout=5_000, state="visible")
                await page.click(selector)
                # Aguarda navegação após clicar
                await page.wait_for_load_state("networkidle", timeout=10_000)
                return
            except Exception:
                continue
        # Se nenhum seletor funcionou, a reunião pode já ter começado
        # ou o usuário já está dentro — segue em frente sem erro fatal.

    # ── Gravação de áudio ──────────────────────────────────────────────────

    async def _inject_audio_capture(self, page) -> None:
        """
        Injeta MediaRecorder no browser para capturar áudio do microfone.
        Os chunks ficam em window.__audioChunks como strings base64.
        """
        await page.evaluate("""
            window.__audioChunks = [];
            window.__recordingActive = false;

            async function startAudioCapture() {
                try {
                    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    const mr = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });

                    mr.ondataavailable = (e) => {
                        if (e.data && e.data.size > 0) {
                            const reader = new FileReader();
                            reader.onloadend = () => {
                                // Armazena apenas a parte base64 (sem o prefixo data:...)
                                const base64 = reader.result.split(',')[1];
                                window.__audioChunks.push(base64);
                            };
                            reader.readAsDataURL(e.data);
                        }
                    };

                    mr.start(5000);  // chunk a cada 5 segundos
                    window.__recordingActive = true;
                    window.__mediaRecorder = mr;
                } catch (e) {
                    console.error('AudioCapture error:', e);
                }
            }

            startAudioCapture();
        """)

    async def _collect_and_save_audio(self, page, session: BotSession) -> None:
        """
        Lê window.__audioChunks do browser, decodifica base64 e salva em disco.
        O arquivo salvo é .webm (opus) — compatível com Whisper via ffmpeg.
        """
        try:
            # Para o MediaRecorder para forçar flush do último chunk
            await page.evaluate("""
                if (window.__mediaRecorder && window.__mediaRecorder.state !== 'inactive') {
                    window.__mediaRecorder.stop();
                }
            """)
            # Dá tempo para o último ondataavailable disparar
            await asyncio.sleep(1)

            chunks: list[str] = await page.evaluate("window.__audioChunks || []")

            if not chunks or session.output_path is None:
                session.error_message = "Nenhum chunk de áudio coletado."
                return

            # Decodifica e concatena os chunks base64 → arquivo binário
            with open(session.output_path, "wb") as f:
                for chunk_b64 in chunks:
                    f.write(base64.b64decode(chunk_b64))

        except Exception as exc:
            session.error_message = f"Erro ao salvar áudio: {exc}"

    # ── Detectar fim da reunião ────────────────────────────────────────────
async def _wait_until_meeting_ends(self, page) -> None:
    initial_count = await self._get_participant_count(page)
    left_count = 0

    while elapsed < self._MAX_RECORDING_SECONDS:
        await asyncio.sleep(self._POLL_INTERVAL_SECONDS)
        elapsed += self._POLL_INTERVAL_SECONDS

        # Verifica seletores de tela de encerramento
        for selector in self._SEL_MEETING_ENDED:
            try:
                if await page.query_selector(selector):
                    return
            except Exception:
                continue

        # Verifica se 3+ participantes saíram
        current_count = await self._get_participant_count(page)
        if current_count < initial_count - 2:  # 3 ou mais saíram
            return

async def _get_participant_count(self, page) -> int:
    """Conta participantes ativos na reunião."""
    try:
        count = await page.evaluate("""
            (() => {
                const participants = document.querySelectorAll(
                    '[data-participant-id], [data-ssrc]'
                );
                return participants.length;
            })()
        """)
        return int(count or 0)
    except Exception:
        return 0
        