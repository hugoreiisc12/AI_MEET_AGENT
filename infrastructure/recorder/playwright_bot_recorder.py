"""
playwright_bot_recorder.py — Bot que grava áudio do Google Meet via Playwright.

Correções aplicadas:
  S1 — Login: launch_persistent_context() com perfil Chrome + _verify_logged_in()
  S2 — Áudio: injeção do audio_capture.js (intercepta <audio> do Meet)
  S3 — Entrega: callback on_audio_ready injetado pelo use case
  S4 — Fim de reunião: 3 sinais combinados (tela de saída, sozinho, silêncio)
  S6 — Etapas documentadas pelo próprio session.status
  S7 — Log temporal de voz/speaker salvo como JSON ao lado do .webm
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

AUDIO_CAPTURE_JS = (Path(__file__).parent / "audio_capture.js").read_text(encoding="utf-8")

OnAudioReady = Callable[[Path, Path], Awaitable[None]]

MEET_STATUS_JS = """
(() => {
  const sel = '[data-self-name][data-speaking="true"]';
  const speaking = [...document.querySelectorAll(sel)].map(el =>
    el.getAttribute('data-self-name') || el.textContent?.trim().split('\\n')[0] || '?'
  );
  const participants = (() => {
    const btn = document.querySelector(
      'button[aria-label*="articipante" i], button[aria-label*="essoas" i], button[aria-label*="people" i]'
    );
    if (!btn) return -1;
    const m = btn.getAttribute('aria-label')?.match(/\\d+/);
    return m ? parseInt(m[0], 10) : -1;
  })();
  const capture = window.__meetCapture;
  const error = capture ? capture._error : null;
  return {
    participants,
    speaking,
    recording: capture ? capture.getState().recording : false,
    audioChunks: capture ? capture.getState().chunks : 0,
    lastAudioTs: capture ? capture.getLastAudioTs() : 0,
    captureError: error,
  };
})();
"""


class BotNotLoggedInError(RuntimeError):
    """Sessão Google expirada/inexistente — rodar bot_setup.py novamente."""


async def _wait_page_stable(page: Page, timeout: float = 5.0) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout * 1000)
    except Exception:
        await page.wait_for_load_state("domcontentloaded", timeout=5000)


def _obs(message: str) -> None:
    logger.info("🔍 %s", message)


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
    ALONE_TIMEOUT = 60
    SILENCE_TIMEOUT = 120
    POLL_INTERVAL = 10
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
            msg = str(exc)
            if "Target page, context or browser has been closed" in msg:
                error = "Navegador fechado inesperadamente. O Chrome pode estar sendo usado em outra janela com o mesmo perfil."
            else:
                error = f"{type(exc).__name__}: {exc}"
            self._set_status("failed", error=error)
            raise
        return self.session

    async def _run_session(self) -> None:
        assert self.session is not None
        _obs("🌐 Iniciando Playwright...")
        async with async_playwright() as pw:
            _obs("📦 Copiando perfil para diretório temporário...")
            import shutil
            import tempfile
            profile_copy = Path(tempfile.mkdtemp(prefix="bot_profile_"))
            shutil.copytree(
                str(self.chrome_profile_dir),
                str(profile_copy),
                ignore=shutil.ignore_patterns(
                    "Cache", "Code Cache", "GPUCache", "ShaderCache",
                    "GrShaderCache", "DawnGraphiteCache", "GraphiteDawnCache",
                    "Crashpad", "Crash Reports", "Session Stats",
                    "chrome_shutdown_ms.txt", "chrome_ms_*.txt",
                ),
                dirs_exist_ok=True,
                ignore_dangling_symlinks=True,
            )
            _obs(f"✅ Perfil copiado para {profile_copy}")

            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(profile_copy),
                headless=self.headless,
                permissions=["microphone", "camera"],
                channel="chrome",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--use-fake-ui-for-media-stream",
                    "--no-sandbox",
                    "--disable-features=ChromeWhatsNewUI",
                    "--auto-select-tab-capture-source-by-title=Google Meet",
                    "--auto-select-desktop-capture-source=Entire screen",
                ],
            )
            _obs("✅ Navegador aberto com perfil do bot")
            try:
                page = context.pages[0] if context.pages else await context.new_page()

                self._set_status("logging_in")
                _obs("🔐 Verificando login Google...")
                await self._verify_logged_in(page)
                _obs("✅ Login OK — sessão Google ativa")

                self._set_status("joining")
                _obs(f"📞 Navegando para: {self.session.meeting_url}")
                await page.goto(
                    self.session.meeting_url, wait_until="domcontentloaded"
                )
                await self._verify_logged_in(page)
                await _wait_page_stable(page)
                _obs("✅ Página da reunião carregada")
                await self._prepare_devices(page)
                await self._click_join_button(page)
                await _wait_page_stable(page)
                await self._wait_admitted(page)
                _obs("🎉 BOT ENTROU NA REUNIÃO!")

                self._set_status("recording")
                _obs("🎙️ Injetando captura de áudio...")
                await self._inject_audio_capture(page)
                _obs("🎙️ Captura de áudio ATIVA — gravando participantes remotos")

                self._set_status("monitoring")
                _obs("📊 Monitoramento da reunião iniciado (a cada 10s)")
                await self._wait_until_meeting_ends(page)
                _obs("🛑 FIM DA REUNIÃO DETECTADO")

                self._set_status("saving")
                _obs("💾 Salvando gravação...")
                await self._collect_and_save_audio(page)
                _obs("✅ Áudio salvo em disco")

                self._set_status("delivering")
                _obs("📤 Entregando áudio para processamento...")
                await self._deliver()
                _obs("✅ Entrega concluída")

                self._set_status("done")
                _obs("🏁 Bot finalizado com sucesso!")
            finally:
                _obs("🧹 Fechando navegador...")
                await context.close()
                _obs("✅ Navegador fechado")
                try:
                    shutil.rmtree(str(profile_copy), ignore_errors=True)
                    _obs("🧹 Perfil temporário removido")
                except Exception:
                    pass

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
        _obs("🔇 Desabilitando microfone e câmera do bot...")
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
        _obs("✅ Mic/Cam desligados")

    async def _fill_name_if_needed(self, page: Page) -> None:
        name_input = page.locator(
            'input[aria-label*="Seu nome" i], '
            'input[aria-label*="Your name" i], '
            'input[aria-label*="Nome" i]'
        )
        try:
            if await name_input.count() > 0 and await name_input.first.is_visible():
                current = await name_input.first.input_value()
                if not current.strip():
                    _obs(f"✏️ Preenchendo nome do bot: {self.bot_name}")
                    await name_input.first.fill(self.bot_name)
                    await asyncio.sleep(1)
        except Exception:
            pass

    async def _diagnose_pre_join_screen(self, page: Page) -> None:
        try:
            url = page.url
            buttons = await page.evaluate(
                """() => [...document.querySelectorAll('button')]
                    .map(b => ({ text: b.innerText.slice(0, 50), disabled: b.disabled }))
                    .filter(b => b.text.trim())"""
            )
            inputs = await page.evaluate(
                """() => [...document.querySelectorAll('input')]
                    .map(i => ({ aria: i.getAttribute('aria-label') || '', value: i.value.slice(0, 30) }))
                    .filter(i => i.aria)"""
            )
            heading = await page.evaluate(
                "document.querySelector('h1, h2, h3, [role=heading]')?.innerText?.slice(0, 100) || 'N/A'"
            )
            _obs(f"📋 URL: {url}")
            _obs(f"📋 Título: {heading}")
            _obs(f"📋 Botões: {json.dumps(buttons, ensure_ascii=False)}")
            _obs(f"📋 Inputs: {json.dumps(inputs, ensure_ascii=False)}")
        except Exception as e:
            _obs(f"⚠️ Diagnóstico: página indisponível ({e})")

    async def _ensure_page_ready(self, page: Page) -> None:
        _obs("🔧 Garantindo que todos os campos estejam preenchidos...")
        try:
            inputs = await page.evaluate("""
                () => [...document.querySelectorAll('input[type=text], input:not([type])')]
                    .map(i => ({
                        aria: i.getAttribute('aria-label') || '',
                        placeholder: i.placeholder || '',
                        value: i.value.slice(0, 30),
                        id: i.id
                    }))
                    .filter(i => i.aria || i.placeholder)
            """)
            for inp in inputs:
                if not inp["value"].strip():
                    selector = f'#{inp["id"]}' if inp["id"] else f'input[aria-label="{inp["aria"]}"]'
                    try:
                        field = page.locator(selector)
                        if await field.is_visible():
                            await field.fill(self.bot_name)
                            _obs(f"✏️ Preenchido campo: {inp['aria'] or inp['placeholder']}")
                    except Exception:
                        pass
        except Exception:
            pass

    async def _click_join_button(self, page: Page) -> None:
        await self._ensure_page_ready(page)

        join_texts = [
            "Participar agora", "Pedir para participar",
            "Join now", "Ask to join"
        ]
        join_any = page.locator(
            ", ".join(f'button:has-text("{t}")' for t in join_texts)
        )

        for tentativa in range(5):
            try:
                if await join_any.first.is_visible():
                    _obs(f"🖱️ Clicando botão (tentativa {tentativa+1})")
                    await join_any.first.click(force=True, timeout=5000)
                    _obs("✅ Botão clicado")
                    return
            except Exception as e:
                _obs(f"⏳ Botão não respondeu: {type(e).__name__}")
            await asyncio.sleep(2)

        await self._diagnose_pre_join_screen(page)
        raise RuntimeError(
            f"Não foi possível entrar na reunião após 5 tentativas. "
            f"Verifique o código ou se o organizador já iniciou."
        )

    async def _wait_admitted(self, page: Page) -> None:
        in_call = page.locator(
            '[aria-label*="Sair da chamada" i], [aria-label*="Leave call" i]'
        )
        waiting = page.locator(
            '[aria-label*="Cancelar" i], [aria-label*="Cancel request" i], '
            'button:has-text("Sair da sala de espera"), '
            'button:has-text("Leave waiting room")'
        )
        deadline = time.monotonic() + (self.JOIN_TIMEOUT / 1000)
        while time.monotonic() < deadline:
            try:
                if await in_call.first.is_visible():
                    _obs("✅ Admitido na reunião!")
                    return
                if await waiting.first.is_visible():
                    _obs("⏳ Na sala de espera — aguardando organizador aprovar...")
                else:
                    page_text = await page.evaluate("document.body?.innerText?.slice(0, 500) || ''")
                    if "não é possível participar" in page_text.lower():
                        raise RuntimeError(
                            "Google Meet bloqueou entrada: 'Não é possível participar desta videochamada'. "
                            "A reunião pode exigir conta específica, pode ter sido encerrada, ou o bot não tem permissão."
                        )
                    _obs(f"⏳ Aguardando entrada na reunião... +{int(deadline - time.monotonic())}s restantes")
            except RuntimeError:
                raise
            except Exception:
                pass
            await asyncio.sleep(10)
        raise RuntimeError(
            "Tempo limite excedido aguardando entrada na reunião "
            f"({self.JOIN_TIMEOUT/1000}s). O organizador pode não ter aprovado."
        )

    async def _inject_audio_capture(self, page: Page) -> None:
        await page.evaluate(AUDIO_CAPTURE_JS)
        await asyncio.sleep(3)
        await page.evaluate("window.__meetCapture._resume()")
        await asyncio.sleep(2)
        cap_state = await page.evaluate("window.__meetCapture.getState()")
        cap_error = await page.evaluate("window.__meetCapture._error")
        _obs(
            f"Estado da captura: gravando={cap_state.get('recording')}, "
            f"chunks de áudio={cap_state.get('chunks')}, "
            f"erro={cap_error}"
        )
        if cap_error:
            raise RuntimeError(f"Falha na captura de áudio: {cap_error}")
        if not cap_state.get("recording"):
            raise RuntimeError(f"MediaRecorder não iniciou: {cap_state}")

    async def _get_status_snapshot(self, page: Page) -> dict:
        try:
            return await page.evaluate(MEET_STATUS_JS)
        except Exception:
            return {}

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
        loop_count = 0

        while True:
            await asyncio.sleep(self.POLL_INTERVAL)
            loop_count += 1

            if await self._ended_screen_visible(page):
                _obs("🚪 Tela de encerramento detectada — reunião foi encerrada")
                return

            snapshot = await self._get_status_snapshot(page)
            count = snapshot.get("participants", -1)
            speaking = snapshot.get("speaking", [])
            recording = snapshot.get("recording", False)
            cap_error = snapshot.get("captureError")
            chunks = snapshot.get("audioChunks", 0)
            last_audio_ts = snapshot.get("lastAudioTs", 0)
            silence = time.time() - (last_audio_ts / 1000) if last_audio_ts else 0

            status_parts = [f"👥 Participantes: {count if count >= 0 else '?'}"]
            if speaking:
                status_parts.append(f"🗣️ Falando: {', '.join(speaking[:3])}")
            else:
                status_parts.append("🔇 Ninguém falando")
            status_parts.append(f"🎵 {chunks} chunk(s)")
            if cap_error:
                status_parts.append(f"❌ {cap_error}")
            if silence > 0:
                status_parts.append(f"⏳ Silêncio: {silence:.0f}s")
            status_parts.append(f"⏱️ Tick #{loop_count}")
            _obs(" | ".join(status_parts))

            if count == 1:
                alone_since = alone_since or time.monotonic()
                alone_for = time.monotonic() - alone_since
                _obs(f"⏰ Sozinho há {alone_for:.0f}s (limite: {self.ALONE_TIMEOUT}s)")
                if alone_for >= self.ALONE_TIMEOUT:
                    _obs("🏁 Reunião vazia — bot sozinho por tempo suficiente")
                    return
            else:
                if count > 1 and alone_since is not None:
                    _obs(f"👤 Novo participante entrou — cancelando detecção de vazio")
                alone_since = None

            if silence >= self.SILENCE_TIMEOUT:
                _obs(f"🔇 Silêncio total de {silence:.0f}s — reunião encerrada por inatividade")
                return

    async def _collect_and_save_audio(self, page: Page) -> None:
        assert self.session is not None
        _obs("🛑 Parando MediaRecorder e coletando áudio...")
        b64: str = await page.evaluate("window.__meetCapture.stop()")

        audio_path = self.audio_dir / f"{self.session.id}.webm"
        audio_path.write_bytes(base64.b64decode(b64))
        size_kb = audio_path.stat().st_size / 1024
        _obs(f"💾 Áudio salvo: {audio_path.name} ({size_kb:.1f} KB)")

        speaker_log = await page.evaluate("window.__meetCapture.getSpeakerLog()")
        log_path = self.audio_dir / f"{self.session.id}.speakers.json"
        log_path.write_text(
            json.dumps(speaker_log, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        speakers_set = set()
        for entry in speaker_log:
            for s in entry.get("speakers", []):
                speakers_set.add(s)
        _obs(
            f"🗣️ Log de falas: {len(speaker_log)} eventos, "
            f"{len(speakers_set)} falante(s) detectado(s): "
            f"{', '.join(sorted(speakers_set)) if speakers_set else 'N/A'}"
        )

        self.session.audio_path = audio_path
        self.session.speaker_log_path = log_path

    async def _deliver(self) -> None:
        assert self.session is not None
        if self.on_audio_ready and self.session.audio_path:
            _obs("📤 Chamando callback de entrega...")
            await self.on_audio_ready(
                self.session.audio_path, self.session.speaker_log_path
            )
            _obs("✅ Callback de entrega concluído")

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
