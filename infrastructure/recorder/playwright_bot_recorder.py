"""

Este módulo contém a implementação do `PlaywrightBotRecorder` usada para
entrar em chamadas do Google Meet e coletar áudio localmente.

Fluxo:
    join_async()
          run_session()
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
    recording_started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_message: str = ""
    audio_chunks: list[str] = field(default_factory=list, repr=False)
    participant_info: dict[str, str] = field(default_factory=dict)
    speaker_observations: list[dict[str, float | str]] = field(default_factory=list)

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
        'button:has-text("Entrar")',
        'button:has-text("Join")',
    ]

    _SEL_MUTE_BTN = [
        'button[aria-label*="Microfone"]',
        'button[aria-label*="microphone"]',
        'button[aria-label*="Mute"]',
        'button[aria-label*="Unmute"]',
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
                    "--disable-background-timer-throttling",
                    "--disable-renderer-backgrounding",
                    "--disable-backgrounding-occluded-windows",
                    "--autoplay-policy=no-user-gesture-required",
                ],
            )
            page = await context.new_page()

            try:
                # 1. Navega para a reunião
                await page.goto(session.meeting_url, wait_until="networkidle", timeout=30_000)

                # 2. Verifica se o perfil já está logado no Google antes de entrar
                await self._ensure_logged_in(page)

                # 3. Garante que o bot está com microfone mudo antes de entrar
                await self._mute_before_join(page)

                # 4. Entra na sala automaticamente
                session.status = "joining"
                await self._click_join_button(page)

                # 5. Lê participantes e conta quantos estão na reunião
                session.participant_info = await self._collect_participants(page)
                current_count = await self._get_participant_count(page)

                # 6. Inicia captura de áudio no browser e inicia amostragem do speaker ativo
                session.status = "recording"
                await self._inject_audio_capture(page)
                session.recording_started_at = datetime.now()
                active_speaker_task = asyncio.create_task(
                    self._sample_active_speaker(page, session)
                )

                # 7. Aguarda a reunião terminar (ou timeout)
                await self._wait_until_meeting_ends(page, current_count)

                # 8. Garante parada da amostragem antes de salvar o áudio
                active_speaker_task.cancel()
                try:
                    await active_speaker_task
                except asyncio.CancelledError:
                    pass

                # 9. Coleta chunks gravados e salva em disco
                await self._collect_and_save_audio(page, session)

            finally:
                # Garante que o contexto sempre fecha, mesmo em erro
                await context.close()

        # 9. Marca sessão como concluída — _watch() em RecordMeetingUC detecta aqui
        if session.error_message:
            session.status = "error"
        else:
            session.status = "done"
        session.finished_at = datetime.now()

    #  Entrar na reunião 

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

        # Tentativa fallback mais agressiva no caso do Meet mudar o seletor
        try:
            await page.evaluate("""
                (() => {
                    const buttons = Array.from(document.querySelectorAll('button'));
                    const joinButton = buttons.find(el => {
                        const text = (el.innerText || el.getAttribute('aria-label') || '').toLowerCase();
                        return /participar agora|entrar agora|join now|join|participar/.test(text);
                    });
                    if (joinButton) {
                        joinButton.click();
                    }
                })();
            """)
            await page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            # Se nenhum seletor funcionou, a reunião pode já ter começado
            # ou o usuário já está dentro — segue em frente sem erro fatal.
            pass

    async def _ensure_logged_in(self, page) -> None:
        """Verifica se o perfil do bot já está logado no Google Meet."""
        try:
            sign_in_prompt = await page.query_selector('input[type="email"], input[type="password"], button[jsname="LgbsSe"]')
            if sign_in_prompt:
                raise RuntimeError(
                    "Bot não está logado no Google. Faça login no perfil do bot antes de rodar." 
                    f"Veja o perfil em: {self._profile_dir}"
                )
        except Exception as exc:
            if isinstance(exc, RuntimeError):
                raise
            return

    async def _mute_before_join(self, page) -> None:
        """Tenta silenciar o microfone automaticamente antes de entrar."""
        for selector in self._SEL_MUTE_BTN:
            try:
                button = await page.query_selector(selector)
                if not button:
                    continue
                label = (await button.get_attribute("aria-label") or "").lower()
                if "microfone" in label or "microphone" in label or "mute" in label:
                    if "desativar" in label or "mute microphone" in label or "mudo" in label:
                        await button.click()
                        return
            except Exception:
                continue

        try:
            await page.evaluate("""
                (() => {
                    const buttons = Array.from(document.querySelectorAll('button'));
                    const muteButton = buttons.find(el => {
                        const label = (el.getAttribute('aria-label') || '').toLowerCase();
                        return /microfone|microphone|mute|mudo/.test(label);
                    });
                    if (muteButton) {
                        const label = (muteButton.getAttribute('aria-label') || '').toLowerCase();
                        if (/desativar|mute microphone|mute|mudo/.test(label)) {
                            muteButton.click();
                        }
                    }
                })();
            """)
        except Exception:
            pass

    #  Gravação de áudio 

    async def _inject_audio_capture(self, page) -> None:
        """
        Injeta MediaRecorder no browser para capturar áudio.
        Usa captura de aba/sistema sempre que possível e cai para o microfone local.
        Os chunks ficam em window.__audioChunks como strings base64.

        Nota: getUserMedia({ audio: true }) captura o microfone local.
        Para capturar áudio do Meet, é necessário um fluxo de captura de aba/sistema.
        """
        await page.evaluate("""
            window.__audioChunks = [];
            window.__recordingActive = false;

            async function startAudioCapture() {
                try {
                    let stream;
                    try {
                        stream = await navigator.mediaDevices.getDisplayMedia({ audio: true, video: false });
                    } catch (err) {
                        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    }

                    const mr = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });

                    mr.ondataavailable = (e) => {
                        if (e.data && e.data.size > 0) {
                            const reader = new FileReader();
                            reader.onloadend = () => {
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

    async def _collect_participants(self, page) -> dict[str, str]:
        """Coleta participantes visíveis no Meet com ID e label preferindo email."""
        try:
            entries = await page.evaluate(r"""
                (() => {
                    const emailRegex = /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/;
                    const normalize = (value) => (value || '').toString().trim();
                    const tiles = Array.from(document.querySelectorAll('[data-participant-id]'));
                    return tiles
                        .filter(el => el.offsetParent !== null)
                        .map(el => {
                            const id = el.getAttribute('data-participant-id') || el.dataset.participantId || '';
                            if (!id) return null;
                            const email = normalize(el.getAttribute('data-participant-email') || el.dataset.participantEmail);
                            const name = normalize(el.getAttribute('data-participant-name') || el.dataset.participantName);
                            const aria = normalize(el.getAttribute('aria-label'));
                            const text = normalize(el.innerText);
                            let label = email || name || aria || text || id;
                            const emailMatch = label.match(emailRegex);
                            if (emailMatch) {
                                label = emailMatch[0];
                            }
                            return { id, label };
                        })
                        .filter(Boolean);
                })()
            """)
            return {entry['id']: entry['label'] for entry in entries if entry and entry.get('id')}
        except Exception:
            return {}

    async def _get_active_speaker(self, page) -> str | None:
        """Retorna o participant-id do speaker ativo visível no Meet, se puder detectar."""
        try:
            active_id = await page.evaluate(r"""
                (() => {
                    const emailRegex = /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/;
                    const normalize = (value) => (value || '').toString().trim();
                    const tiles = Array.from(document.querySelectorAll('[data-participant-id]'));
                    const visible = tiles.filter(el => el.offsetParent !== null);
                    const candidates = visible.length ? visible : tiles;

                    const getLabel = (el) => {
                        const email = normalize(el.getAttribute('data-participant-email') || el.dataset.participantEmail);
                        const name = normalize(el.getAttribute('data-participant-name') || el.dataset.participantName);
                        const aria = normalize(el.getAttribute('aria-label'));
                        const text = normalize(el.innerText);
                        let label = email || name || aria || text;
                        const emailMatch = label.match(emailRegex);
                        if (emailMatch) {
                            label = emailMatch[0];
                        }
                        return label;
                    };

                    const active = candidates.find(el => {
                        const aria = normalize(el.getAttribute('aria-label')).toLowerCase();
                        const cls = normalize(el.className).toLowerCase();
                        return aria.includes('falando')
                            || aria.includes('speaking')
                            || cls.includes('active-speaker')
                            || cls.includes('active')
                            || cls.includes('speaking');
                    });

                    if (active && active.getAttribute('data-participant-id')) {
                        return active.getAttribute('data-participant-id');
                    }

                    return null;
                })()
            """)
            return active_id or None
        except Exception:
            return None

    async def _sample_active_speaker(self, page, session: BotSession) -> None:
        """Amostra o speaker ativo periodicamente para inferir quem fala em cada intervalo."""
        while True:
            speaker_id = await self._get_active_speaker(page)
            if speaker_id and session.recording_started_at:
                offset = (datetime.now() - session.recording_started_at).total_seconds()
                session.speaker_observations.append({
                    "timestamp": round(offset, 3),
                    "participant_id": speaker_id,
                })
            await asyncio.sleep(2)

    #  Detectar fim da reunião
    async def _wait_until_meeting_ends(self, page, initial_count: int) -> None:
        elapsed = 0
        solo_counter = 0

        while elapsed < self._MAX_RECORDING_SECONDS:
            await asyncio.sleep(self._POLL_INTERVAL_SECONDS)
            elapsed += self._POLL_INTERVAL_SECONDS

            if await self._is_meeting_ended_screen(page):
                return

            current_count = await self._get_participant_count(page)
            if initial_count > 0 and current_count == 0:
                return

            # Se só restar o bot sozinho na chamada por alguns ciclos, considera fim.
            if initial_count > 1 and current_count <= 1:
                solo_counter += 1
            else:
                solo_counter = 0

            if solo_counter >= 2:
                return

        # Timeout máximo atingido, finaliza com o áudio salvo até aqui.

    async def _get_participant_count(self, page) -> int:
        """Conta participantes ativos na reunião com seletor mais específico."""
        try:
            count = await page.evaluate("""
                (() => {
                    const participants = Array.from(document.querySelectorAll('[data-participant-id]'));
                    return participants.filter(el => el.offsetParent !== null).length;
                })()
            """)
            return int(count or 0)
        except Exception:
            return 0

    async def _is_meeting_ended_screen(self, page) -> bool:
        """Detecta telas de reunião encerrada ou retorno à tela inicial."""
        for selector in self._SEL_MEETING_ENDED:
            try:
                element = await page.query_selector(selector)
                if element:
                    return True
            except Exception:
                continue

        try:
            return await page.evaluate("""
                (() => {
                    const text = document.body.innerText.toLowerCase();
                    return text.includes('you left the video call')
                        || text.includes('você saiu da videochamada')
                        || text.includes('return to home screen')
                        || text.includes('back to home screen')
                        || text.includes('call ended')
                        || text.includes('you are the only participant');
                })()
            """)
        except Exception:
            return False
        