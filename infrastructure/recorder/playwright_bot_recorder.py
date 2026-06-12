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
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Optional

from playwright.async_api import BrowserContext, Page, async_playwright

logger = logging.getLogger(__name__)

AUDIO_CAPTURE_JS = (Path(__file__).parent / "audio_capture.js").read_text(encoding="utf-8")

# Injetado via add_init_script (antes do Meet carregar) para interceptar
# tracks de áudio WebRTC antes que a página as consuma.
RTC_PATCH_JS = """
(() => {
  if (window.__rtcPatched) return;
  window.__rtcPatched = true;
  window.__rtcAudioTracks = [];
  const Orig = window.RTCPeerConnection;
  if (!Orig) return;
  function Patched() {
    const pc = new Orig(...arguments);
    pc.addEventListener('track', function(ev) {
      if (ev.track && ev.track.kind === 'audio') {
        window.__rtcAudioTracks.push(ev.track);
        console.log('[rtcPatch] audio track:', ev.track.id, ev.track.readyState);
      }
    });
    return pc;
  }
  Patched.prototype = Orig.prototype;
  if (Orig.generateCertificate) Patched.generateCertificate = Orig.generateCertificate.bind(Orig);
  window.RTCPeerConnection = Patched;
  console.log('[rtcPatch] RTCPeerConnection interceptado');
})();
"""

CAPTION_CAPTURE_JS = """
(() => {
  if (window.__meetCaptions) return;

  const log = [];
  let lastTs = 0;
  const lastBySpeaker = {};

  function extractFromDOM() {
    const strats = [
      () => {
        const out = [];
        document.querySelectorAll('[jsname="tgaKEf"]').forEach(el => {
          const text = el.innerText?.trim();
          if (!text) return;
          const root = el.closest('[data-sender-name], [data-participant-id]');
          const speaker = root?.getAttribute('data-sender-name')
            || root?.querySelector('[data-self-name]')?.getAttribute('data-self-name')
            || 'Unknown';
          out.push({ speaker, text });
        });
        return out;
      },
      () => {
        const out = [];
        document.querySelectorAll('.a4cQT, .Gn1jf').forEach(el => {
          const text = el.innerText?.trim();
          const speaker = el.closest('[data-sender-name]')?.getAttribute('data-sender-name') || 'Unknown';
          if (text) out.push({ speaker, text });
        });
        return out;
      },
      () => {
        const out = [];
        document.querySelectorAll('[class*="caption" i] span, [class*="subtitle" i] span').forEach(el => {
          const text = el.innerText?.trim();
          if (text && text.length > 2) out.push({ speaker: 'Unknown', text });
        });
        return out;
      },
    ];
    for (const strat of strats) {
      try { const r = strat(); if (r.length) return r; } catch (_) {}
    }
    return [];
  }

  function onMutation() {
    const now = Date.now();
    for (const { speaker, text } of extractFromDOM()) {
      const prev = lastBySpeaker[speaker];
      if (prev && now - prev.ts < 3000) {
        const idx = log.findIndex(e => e.speaker === speaker && e.ts_ms === prev.ts);
        if (idx >= 0 && log[idx].text !== text) { log[idx].text = text; lastTs = now; }
        continue;
      }
      lastBySpeaker[speaker] = { ts: now, text };
      log.push({ speaker, text, ts_ms: now, ts_readable: new Date(now).toISOString() });
      lastTs = now;
    }
  }

  const obs = new MutationObserver(onMutation);
  obs.observe(document.documentElement, { childList: true, subtree: true, characterData: true });

  window.__meetCaptions = {
    getLog: () => log,
    getLastTs: () => lastTs,
    count: () => log.length,
  };
  console.log('[meetCaptions] ativo');
})();
"""

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
    caption_path: Optional[Path] = None

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
    CAPTION_POLL_INTERVAL = 1.0

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
        self._caption_log: list = []
        self._last_caption_ts: float = 0.0

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
            await context.add_init_script(script=RTC_PATCH_JS)
            _obs("✅ Interceptor WebRTC registrado")
            try:
                page = context.pages[0] if context.pages else await context.new_page()

                self._set_status("logging_in")
                _obs("🔐 Verificando login Google...")
                await self._verify_logged_in(page)
                _obs("✅ Login OK — sessão Google ativa")

                self._set_status("joining")
                _obs(f" Navegando para: {self.session.meeting_url}")
                await page.goto(
                    self.session.meeting_url, wait_until="domcontentloaded"
                )
                _obs("⏳ Aguardando 20s para página carregar completamente...")
                await asyncio.sleep(20)
                try:
                    await self._verify_logged_in(page)
                except BotNotLoggedInError:
                    _obs("🔑 Sessão expirada — tentando login automático...")
                    await self._auto_login(page)
                    _obs("✅ Login automático concluído")
                    # Aguarda recarregar a página da reunião
                    await page.goto(
                        self.session.meeting_url, wait_until="domcontentloaded"
                    )
                    await asyncio.sleep(10)
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

                _obs("📝 Ativando legendas...")
                await self._activate_captions(page)

                self._set_status("monitoring")
                _obs("📊 Monitoramento da reunião iniciado (a cada 10s)")
                caption_task = asyncio.create_task(self._capture_captions_loop(page))
                try:
                    await self._wait_until_meeting_ends(page)
                finally:
                    caption_task.cancel()
                    try:
                        await caption_task
                    except asyncio.CancelledError:
                        pass
                _obs("🛑 FIM DA REUNIÃO DETECTADO")

                self._set_status("saving")
                _obs("💾 Salvando gravação...")
                await self._collect_and_save_audio(page)
                self._save_captions()
                _obs("✅ Áudio e legendas salvos em disco")

                self._set_status("delivering")
                _obs("📤 Entregando para processamento...")
                await self._deliver()
                await self._deliver_captions()
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
        # Google usa div, button ou a para "Fazer login" — checa todos
        login_texts = page.locator(
            'a:has-text("Fazer login"), a:has-text("Sign in"), '
            'div:has-text("Fazer login"), div:has-text("Sign in"), '
            'button:has-text("Fazer login"), button:has-text("Sign in")'
        )
        if await login_texts.count() > 0 and await login_texts.first.is_visible():
            raise BotNotLoggedInError(
                "Página do Meet exibindo 'Fazer login' — sessão inválida. "
                "Rode novamente: python -m infrastructure.recorder.bot_setup"
            )

    async def _auto_login(self, page: Page) -> None:
        _obs("🔑 Iniciando login automático...")
        email = os.environ.get("BOT_GOOGLE_EMAIL", "")
        password = os.environ.get("BOT_GOOGLE_PASSWORD", "")
        if not email or not password:
            _obs("❌ BOT_GOOGLE_EMAIL/PASSWORD não configurados no .env")
            raise BotNotLoggedInError(
                "Credenciais não encontradas. Configure BOT_GOOGLE_EMAIL e "
                "BOT_GOOGLE_PASSWORD no .env e rode bot_setup.py primeiro."
            )
        # Navega diretamente para página de login do Google
        _obs("🔑 Navegando para accounts.google.com...")
        await page.goto("https://accounts.google.com/signin", wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # Se houver seletor de conta, clica "Usar outra conta"
        try:
            outra_conta = page.locator('[jsname="dRO4D"], text="Usar outra conta", text="Use another account"')
            if await outra_conta.first.is_visible(timeout=3000):
                await outra_conta.first.click()
                await asyncio.sleep(1)
        except Exception:
            pass

        # Preenche email e avança com Enter
        try:
            email_field = page.locator('input[type="email"], #identifierId')
            await email_field.first.wait_for(timeout=10000)
            await email_field.first.fill(email)
            await asyncio.sleep(1)
            await page.keyboard.press("Enter")
            await asyncio.sleep(3)
        except Exception as e:
            _obs(f"⚠️ Erro no campo de email: {e}")
            raise

        # Preenche senha e avança com Enter
        try:
            pw_field = page.locator('input[type="password"]')
            await pw_field.first.wait_for(timeout=10000)
            await pw_field.first.fill(password)
            await asyncio.sleep(1)
            await page.keyboard.press("Enter")
            await asyncio.sleep(3)
        except Exception as e:
            _obs(f"⚠️ Erro no campo de senha: {e}")
            raise

        _obs("✅ Login no Google concluído")

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
                """() => [...document.querySelectorAll('button, [role=button], span.cXqkTb, div.uArJnb')]
                    .map(b => ({ text: b.innerText.slice(0, 60), disabled: b.disabled, tag: b.tagName }))
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
            page_text = await page.evaluate("document.body?.innerText?.slice(0, 2000) || ''")
            print("\n========== DIAGNÓSTICO PRE-JOIN ==========", flush=True)
            print(f"URL: {url}", flush=True)
            print(f"Título: {heading}", flush=True)
            print(f"Botões: {json.dumps(buttons, ensure_ascii=False)}", flush=True)
            print(f"Inputs: {json.dumps(inputs, ensure_ascii=False)}", flush=True)
            print(f"Texto:\n{page_text}", flush=True)
            print("=========================================", flush=True)
            try:
                await page.screenshot(path="pre_join_debug.png", full_page=True)
                print(">>> Screenshot salvo: pre_join_debug.png", flush=True)
            except Exception:
                pass
        except Exception as e:
            print(f"⚠️ Diagnóstico: página indisponível ({e})", flush=True)

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

    async def _already_in_call(self, page: Page) -> bool:
        """Retorna True se o bot já está dentro da chamada.

        Usa o botão 'Sair da chamada' como sinal primário (mais confiável
        do que vasculhar o innerText, que pode não conter o texto no viewport).
        """
        try:
            btn = page.locator(
                '[aria-label*="Sair da chamada" i], [aria-label*="Leave call" i]'
            )
            if await btn.count() > 0 and await btn.first.is_visible():
                return True
        except Exception:
            pass
        # Fallback: texto do corpo com limite maior
        try:
            page_text = await page.evaluate("document.body?.innerText?.slice(0, 3000) || ''")
            return any(frase in page_text for frase in [
                "Sair da chamada", "Leave call",
                "Você está participando da chamada", "You are in the call",
                "Aguarde até que um organizador", "Waiting for the organizer",
            ])
        except Exception:
            return False

    async def _click_join_button(self, page: Page) -> None:
        await self._ensure_page_ready(page)

        # Fecha popups/modais que o Google às vezes exibe
        popup_selectors = [
            "button:has-text('Continuar')",
            "button:has-text('Continue')",
            "button:has-text('Fechar')",
            "button:has-text('Close')",
            "button:has-text('Entendi')",
            "button:has-text('Got it')",
            "div[role=dialog] button:has-text('OK')",
            "div[aria-label*=Alerta] button",
        ]
        for sel in popup_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=1000):
                    await btn.click()
                    _obs(f"🗑️ Popup fechado: {sel}")
            except Exception:
                pass

        # Diagnóstico imediato para ver o estado real da página
        await self._diagnose_pre_join_screen(page)

        # Verificação primária: botão "Sair da chamada" visível = já dentro
        if await self._already_in_call(page):
            _obs("✅ Bot já está dentro da chamada — pulando clique de entrar")
            return

        # Múltiplos seletores para o botão de entrar — Google muda frequentemente
        join_selectors = [
            "button:has-text('Participar agora')",
            "button:has-text('Pedir para participar')",
            "button:has-text('Join now')",
            "button:has-text('Ask to join')",
            "button:has-text('Entrar')",
            "button:has-text('Participar')",
            "button:has-text('Join')",
            '[aria-label*="Participar"i]',
            '[aria-label*="Join"i]',
            "div[role=button]:has-text('Participar agora')",
            "div[role=button]:has-text('Join now')",
            "span.cXqkTb",
            "div.uArJnb",
        ]

        for tentativa in range(5):
            try:
                for selector in join_selectors:
                    btn = page.locator(selector).first
                    if await btn.is_visible():
                        _obs(f"🖱️ Clicando botão '{selector}' (tentativa {tentativa+1})")
                        await btn.click(force=True, timeout=5000)
                        _obs("✅ Botão clicado")
                        return
            except Exception as e:
                _obs(f"⏳ Botão não respondeu: {type(e).__name__}")

            # Re-verifica após cada tentativa: o join pode ter ocorrido
            # durante o clique mesmo sem o botão ter sido detectado
            if await self._already_in_call(page):
                _obs(f"✅ Bot entrou na reunião durante tentativa {tentativa+1}")
                return

            await asyncio.sleep(2)

        # Verificação final antes de lançar erro
        if await self._already_in_call(page):
            _obs("✅ Bot já está dentro da chamada — detectado na verificação final")
            return

        raise RuntimeError(
            "Não foi possível entrar na reunião após 5 tentativas. "
            "Verifique o código ou se o organizador já iniciou."
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

    async def _activate_captions(self, page: Page) -> None:
        cc_selectors = [
            '[aria-label*="Ativar legendas" i]',
            '[aria-label*="Turn on captions" i]',
            '[aria-label*="Legendas" i]',
            '[aria-label*="Captions" i]',
            '[data-tooltip*="legendas" i]',
        ]
        clicked = False
        for sel in cc_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    clicked = True
                    _obs(f"✅ CC ativado via: {sel}")
                    break
            except Exception:
                pass

        if not clicked:
            _obs("⚠️ Botão CC não encontrado — legendas podem já estar ativas")
        else:
            await asyncio.sleep(2)
            await self._ensure_captions_language(page)

        await page.evaluate(CAPTION_CAPTURE_JS)
        _obs("✅ Observer de legendas injetado")

    async def _ensure_captions_language(self, page: Page) -> None:
        lang_selectors = [
            '[aria-label*="Idioma da legenda" i]',
            '[aria-label*="Caption language" i]',
            '[aria-label*="Idioma" i]',
        ]
        for sel in lang_selectors:
            try:
                btn = page.locator(sel).first
                if not await btn.is_visible(timeout=2000):
                    continue
                label = (await btn.get_attribute("aria-label")) or ""
                if "Português" in label or "Portuguese" in label:
                    _obs("✅ Legenda já em Português")
                    return
                await btn.click()
                await asyncio.sleep(1)
                ptbr = page.locator('text="Português (Brasil)"').first
                if await ptbr.is_visible(timeout=3000):
                    await ptbr.click()
                    _obs("✅ Idioma de legendas definido para Português (Brasil)")
                return
            except Exception:
                pass
        _obs("⚠️ Seletor de idioma de legendas não encontrado")

    async def _capture_captions_loop(self, page: Page) -> None:
        known_count = 0
        while True:
            try:
                log = await page.evaluate(
                    "window.__meetCaptions ? window.__meetCaptions.getLog() : []"
                )
                if len(log) > known_count:
                    new_entries = log[known_count:]
                    self._caption_log.extend(new_entries)
                    self._last_caption_ts = time.time()
                    known_count = len(log)
                    _obs(f"📝 +{len(new_entries)} legenda(s) — total: {known_count}")
            except Exception as exc:
                _obs(f"⚠️ Erro ao ler legendas: {exc}")
            await asyncio.sleep(self.CAPTION_POLL_INTERVAL)

    def _save_captions(self) -> None:
        assert self.session is not None
        caption_path = self.audio_dir / f"{self.session.id}.captions.json"
        caption_path.write_text(
            json.dumps(self._caption_log, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.session.caption_path = caption_path
        _obs(f"📝 Legendas salvas: {caption_path.name} ({len(self._caption_log)} entradas)")

    async def _deliver_captions(self) -> None:
        assert self.session is not None
        if not self._caption_log:
            _obs("⚠️ Nenhuma legenda capturada — pulando inserção no banco")
            return
        try:
            import os
            from pymongo import MongoClient
            from datetime import datetime
            mongo_uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017/meetagent")
            db_name = os.environ.get("MONGO_DB", "meetagent")
            client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
            db = client[db_name]
            doc = {
                "original_id": self.session.id,
                "tipo": "legenda",
                "conteudo": self._caption_log,
                "created_at": datetime.now().isoformat(),
            }
            result = db.arquivos.insert_one(doc)
            _obs(f"✅ Legendas inseridas no banco — _id: {result.inserted_id}")
            client.close()
        except Exception as exc:
            _obs(f"⚠️ Falha ao inserir legendas no banco: {exc}")

    async def _wait_until_meeting_ends(self, page: Page) -> None:
        alone_since: Optional[float] = None
        recording_started_at: Optional[float] = None
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

            if recording and recording_started_at is None:
                recording_started_at = time.time()

            # Silêncio de áudio: desde o último chunk ou desde início da gravação
            if last_audio_ts:
                audio_silence = time.time() - (last_audio_ts / 1000)
            elif recording_started_at:
                audio_silence = time.time() - recording_started_at
            else:
                audio_silence = 0

            # Silêncio de legenda: desde a última entrada capturada
            caption_silence = (
                (time.time() - self._last_caption_ts)
                if self._last_caption_ts > 0 else 0
            )

            status_parts = [f"👥 Participantes: {count if count >= 0 else '?'}"]
            if speaking:
                status_parts.append(f"🗣️ Falando: {', '.join(speaking[:3])}")
            else:
                status_parts.append("🔇 Ninguém falando")
            status_parts.append(f"🎵 {chunks} chunk(s) | 📝 {len(self._caption_log)} legenda(s)")
            if cap_error:
                status_parts.append(f"❌ {cap_error}")
            status_parts.append(
                f"⏳ Silêncio áudio: {audio_silence:.0f}s | legenda: {caption_silence:.0f}s"
            )
            status_parts.append(f"⏱️ Tick #{loop_count}")
            _obs(" | ".join(status_parts))

            # Encerra por ausência de participantes
            if count == 1:
                alone_since = alone_since or time.monotonic()
                alone_for = time.monotonic() - alone_since
                _obs(f"⏰ Sozinho há {alone_for:.0f}s (limite: {self.ALONE_TIMEOUT}s)")
                if alone_for >= self.ALONE_TIMEOUT:
                    _obs("🏁 Bot sozinho por tempo suficiente — encerrando")
                    return
            else:
                if count > 1 and alone_since is not None:
                    _obs("👤 Novo participante — cancelando detecção de vazio")
                alone_since = None

            # Encerra apenas se AMBOS áudio E legenda estiverem em silêncio.
            # Se legendas nunca iniciaram (caption_silence == 0), conta como
            # "não disponível" e a decisão recai só sobre o áudio.
            audio_ended = audio_silence >= self.SILENCE_TIMEOUT
            caption_ended = (self._last_caption_ts == 0) or (caption_silence >= self.SILENCE_TIMEOUT)

            if audio_ended and caption_ended:
                motivo = (
                    f"áudio {audio_silence:.0f}s + legenda {caption_silence:.0f}s"
                    if self._last_caption_ts > 0
                    else f"áudio {audio_silence:.0f}s (legendas inativas)"
                )
                _obs(f"🔇 Silêncio duplo ({motivo}) — reunião encerrada por inatividade")
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
