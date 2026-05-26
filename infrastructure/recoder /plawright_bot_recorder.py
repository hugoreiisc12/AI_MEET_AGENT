"""Bot que entra na reunião do meet por meio do Playwright e grava o audio localmente.

Fluxo resumido em:
1- Abre o chrome com perfil persistente contra o bot
2- Faz login no Google se ainda não autenticado
3- Entra na reunião pelo link
4- Captura o audio por meio de um web audio API injetada na pagina
5- Detecta o fim da reunião
6- Salva arquivo e manda para o server
"""

# Precisa de: pip install playwright
# playwright install chromium

from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


# Configurações do bot (email, senha, etc) são lidas do arquivo .env usando a classe Settings 
@dataclass
class BotSession:
    """Estado de uma sessão de gravação do bot."""

    meeting_url: str
    output_path: Optional[Path] = None
    status: str = "idle"
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_message: str = ""
    audio_chunks: list[str] = field(default_factory=list, repr=False)

    @property
    def duration_minutes(self) -> float:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return 0.0

# Bot que usa Playwright para entrar no Google Meet e gravar audio localmente 
class PlaywrightBotRecorder:
    """
    Bot que entra no Google Meet como participante real.

    Usa Playwright para controlar um Chrome com uma conta Google dedicada.
    A conta é autenticada uma vez e o perfil é salvo localmente — nas
    próximas execuções o login é automático.

    Parâmetros:
        google_email:    Email da conta Google do bot
        google_password: Senha da conta Google do bot
        profile_dir:     Pasta onde salvar o perfil do Chrome (persistente)
        bot_name:        Nome que aparece na reunião
        output_dir:      Onde salvar os arquivos de áudio gravados
        headless:        False = Chrome visível (recomendado para não ser bloqueado)
    """

    # Seletores do Google Meet para interagir com a interface
    _SEL_JOIN_BTN = [
        '[data-promo-anchor-id="join-button"]',
        'button[jsname="Qx7uuf"]',
        'button:has-text("Participar agora")',
        'button:has-text("Join now")',
        'button:has-text("Ask to join")',
        'button:has-text("Pedir para participar")',
    ]

    _SEL_LEAVE_BTN = [
        '[aria-label*="Sair da chamada"]',
        '[aria-label*="Leave call"]',
        '[jsname="CQylAd"]',
    ]

    _SEL_MIC_BTN = [
        '[aria-label*="desativar microfone"]',
        '[aria-label*="Mute microphone"]',
        '[jsname="BOHaEe"]',
    ]

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

    # Interface publica para iniciar a gravação - bloqueante 
    def join_and_record(self, meeting_url: str) -> BotSession:
        """
        Entra na reunião e grava até ela terminar.
        Bloqueia até a reunião encerrar — use em thread separada.

        Returns:
            BotSession com output_path preenchido e status='done'
        """
        output_path = self._output_dir / f"bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        session = BotSession(meeting_url=meeting_url, output_path=output_path)

        try:
            asyncio.run(self._run_session(session))
        except Exception as exc:
            session.status = "error"
            session.error_message = str(exc)
            session.finished_at = datetime.now()

        return session

    def join_async(self, meeting_url: str) -> tuple[BotSession, threading.Thread]:
        """
        Versão não-bloqueante: retorna session e thread.
        Monitore session.status para saber quando terminou.
        """
        output_path = self._output_dir / f"bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        session = BotSession(meeting_url=meeting_url, output_path=output_path)

        def _run() -> None:
            try:
                asyncio.run(self._run_session(session))
            except Exception as exc:
                session.status = "error"
                session.error_message = str(exc)
                session.finished_at = datetime.now()

        thread = threading.Thread(target=_run, daemon=True, name="meet-bot")
        thread.start()
        return session, thread
    
    # Core assíncrono que controla o fluxo do bot: login, entrar na reunião e gravar

    async def _run_session(self, session: BotSession) -> None:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            # Abre Chrome com perfil persistente (mantém login entre sessões)
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(self._profile_dir),
                headless=self._headless,
                args=[
                    "--use-fake-ui-for-media-stream",  # aceita mic/câmera sem popup
                    "--disable-blink-features=AutomationControlled",  # esconde automação
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--autoplay-policy=no-user-gesture-required",
                ],
                permissions=["microphone", "camera"],
                ignore_https_errors=True,
            )

            page = await context.new_page()

            # Define nome do bot no navegador
            await page.evaluate(
                """
                Object.defineProperty(navigator, 'userAgent', {
                    get: () => navigator.userAgent.replace('HeadlessChrome', 'Chrome')
                });
                """
            )

            # 1. Login no Google (só necessário na primeira vez)
            session.status = "logging_in"
            await self._ensure_logged_in(page)

            # 2. Entra na reunião
            session.status = "joining"
            await self._join_meeting(page, session.meeting_url)

            # 3. Silencia o microfone do bot (ele só ouve, não fala)
            await self._mute_microphone(page)

            # 4. Injeta captura de áudio
            session.status = "recording"
            session.started_at = datetime.now()
            await self._inject_audio_capture(page, session)

            # 5. Aguarda reunião terminar
            await self._wait_for_meeting_end(page, session)

            # 6. Salva o áudio
            session.finished_at = datetime.now()
            self._save_audio(session)
            session.status = "done"

            await context.close()

    # Login do Google ele detecta se já está autenticado e, se não, faz o fluxo completo de login (email + senha)
    async def _ensure_logged_in(self, page) -> None:
        """Verifica se já está logado. Se não, faz login."""
        await page.goto("https://accounts.google.com", wait_until="networkidle")

        # Verifica se já está autenticado
        if "myaccount.google.com" in page.url or await self._is_logged_in(page):
            print("[Bot]  Já autenticado no Google")
            return

        print(f"[Bot] 🔐 Fazendo login com {self._email}...")
        await self._do_login(page)
        print("[Bot]  Login realizado com sucesso")

# verifica se já esta logado no Google 
    async def _is_logged_in(self, page) -> bool:
        """Verifica se a conta já está logada."""
        try:
            await page.goto("https://myaccount.google.com", wait_until="networkidle", timeout=10000)
            return "myaccount.google.com" in page.url
        except Exception:
            return False

    async def _do_login(self, page) -> None:
        """Executa o fluxo completo de login do Google."""
        await page.goto(
            "https://accounts.google.com/signin/v2/identifier",
            wait_until="networkidle",
        )

        # Campo de email
        await page.wait_for_selector('input[type="email"]', timeout=15000)
        await page.fill('input[type="email"]', self._email)
        await page.click('#identifierNext')

        # Campo de senha
        await page.wait_for_selector('input[type="password"]', state="visible", timeout=15000)
        await asyncio.sleep(1)
        await page.fill('input[type="password"]', self._password)
        await page.click('#passwordNext')

        # Aguarda redirecionamento pós-login
        await page.wait_for_url("**/myaccount.google.com**", timeout=30000)

        # Trata verificação em duas etapas se aparecer
        if "challenge" in page.url or "signin/v2/challenge" in page.url:
            raise RuntimeError(
                "Login requer verificação em duas etapas.\n"
                "Faça o login manualmente uma vez para salvar o perfil:\n"
                "  python main.py --bot-setup"
            )
        
    # Entrar na reunião e clicar em participar 

    async def _join_meeting(self, page, meeting_url: str) -> None:
        """Navega para o Meet e clica em participar."""
        print(f"[Bot] 🚪 Entrando na reunião: {meeting_url}")
        await page.goto(meeting_url, wait_until="networkidle")

        # Aguarda página carregar
        await asyncio.sleep(3)

        # Fecha popups de cookies/permissões se aparecerem
        await self._dismiss_popups(page)

        # Tenta clicar no botão de participar
        joined = False
        for selector in self._SEL_JOIN_BTN:
            try:
                btn = await page.wait_for_selector(selector, timeout=5000)
                if btn:
                    await btn.click()
                    joined = True
                    print(f"[Bot]  Clicou em participar ({selector})")
                    break
            except Exception:
                continue

        if not joined:
            # Fallback: tenta via JavaScript
            await page.evaluate(
                """
                const btns = [...document.querySelectorAll('button')];
                const join = btns.find(b =>
                    b.textContent.includes('Participar') ||
                    b.textContent.includes('Join')
                );
                if (join) join.click();
                """
            )

        # Aguarda entrar na reunião
        await asyncio.sleep(5)
        print("[Bot] ✅ Bot está na reunião")

# silencia o microfone do bot para não recusar aúdio, mas também não falar nada
    async def _mute_microphone(self, page) -> None:
        """Silencia o microfone — o bot só grava, não fala."""
        for selector in self._SEL_MIC_BTN:
            try:
                btn = await page.query_selector(selector)
                if btn:
                    await btn.click()
                    print("[Bot] 🔇 Microfone silenciado")
                    return
            except Exception:
                continue

    async def _dismiss_popups(self, page) -> None:
        """Fecha popups comuns que aparecem antes de entrar."""
        popup_selectors = [
            'button:has-text("Aceitar tudo")',
            'button:has-text("Accept all")',
            'button:has-text("Recusar tudo")',
            '[aria-label="Close"]',
        ]
        for sel in popup_selectors:
            try:
                btn = await page.query_selector(sel)
                if btn:
                    await btn.click()
                    await asyncio.sleep(0.5)
            except Exception:
                pass

    # Captura de audio via Web Audio API injetada na pagina , o audio é exposto em window
    async def _inject_audio_capture(self, page, session: BotSession) -> None:
        """
        Injeta JavaScript que captura o áudio da reunião via Web Audio API
        e expõe os chunks via window.__audioChunks para o Python coletar.
        """
        await page.evaluate(
            """
            window.__audioChunks = [];
            window.__isRecording = false;

            async function startAudioCapture() {
                try {
                    // Captura o stream de áudio de todos os participantes
                    const stream = await navigator.mediaDevices.getUserMedia({
                        audio: {
                            echoCancellation: false,
                            noiseSuppression: false,
                            sampleRate: 16000,
                        }
                    });

                    const mediaRecorder = new MediaRecorder(stream, {
                        mimeType: 'audio/webm;codecs=opus'
                    });

                    mediaRecorder.ondataavailable = (e) => {
                        if (e.data.size > 0) {
                            // Converte Blob para base64 para transferir ao Python
                            const reader = new FileReader();
                            reader.onloadend = () => {
                                window.__audioChunks.push(reader.result);
                            };
                            reader.readAsDataURL(e.data);
                        }
                    };

                    mediaRecorder.start(5000);  // chunk a cada 5s
                    window.__isRecording = true;
                    window.__recorder = mediaRecorder;
                    console.log('[MeetAgent] Gravação iniciada');
                } catch(err) {
                    console.error('[MeetAgent] Erro na gravação:', err);
                }
            }

            startAudioCapture();
            """
        )
        print("[Bot] 🎙 Captura de áudio iniciada")

# coleta os chunks de audio de 5 em 5 segundos para evitar perder dados caso a reunião seja longa ou o bot
    async def _collect_audio_chunks(self, page, session: BotSession) -> None:
        """Coleta chunks de áudio acumulados no browser."""
        try:
            chunks = await page.evaluate("window.__audioChunks.splice(0)")
            if chunks:
                session.audio_chunks.extend(chunks)
        except Exception:
            pass

    # Detecta o fim da reunião reunião monitoramento a URL, e elementos  indicando que a reunião acabou
    async def _wait_for_meeting_end(self, page, session: BotSession) -> None:
        """
        Aguarda a reunião terminar monitorando:
          1. URL mudou (saiu do Meet)
          2. Botão "Voltar para a tela inicial" apareceu
          3. Todos os participantes saíram
        """
        print("[Bot] ⏳ Aguardando reunião terminar...")

        poll_interval = 10  # segundos
        max_wait = 8 * 3600  # 8 horas máximo

        elapsed = 0
        while elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            # Coleta chunks de áudio periodicamente
            await self._collect_audio_chunks(page, session)

            # Verifica se reunião terminou
            ended = await self._check_meeting_ended(page)
            if ended:
                print(f"[Bot] Reunião encerrada ({elapsed}s de duração)")
                # Coleta chunks finais
                await self._collect_audio_chunks(page, session)
                return

        print("[Bot]  Timeout — saindo da reunião")

    async def _check_meeting_ended(self, page) -> bool:
        """Retorna True se a reunião terminou."""
        try:
            current_url = page.url

            # URL mudou para fora do Meet ( o que as vezes pode acontecer é de o google redirecionar para uma pagina de erro)
            if "meet.google.com" not in current_url:
                return True

            # Verifica se apareceu tela de "reunião encerrada"
            ended = await page.evaluate(
                """
                const indicators = [
                    // Tela de fim de reunião
                    document.querySelector('[data-meeting-ended]'),
                    // Botão voltar para tela inicial
                    [...document.querySelectorAll('button')].find(
                        b => b.textContent.includes('Voltar') ||
                             b.textContent.includes('Return') ||
                             b.textContent.includes('Rejoin')
                    ),
                    // Mensagem de reunião encerrada
                    [...document.querySelectorAll('div, span, h1, h2')].find(
                        el => el.textContent.includes('A chamada foi encerrada') ||
                              el.textContent.includes('The call has ended') ||
                              el.textContent.includes('Left the meeting')
                    ),
                ];
                indicators.some(el => el !== null && el !== undefined)
                """
            )
            return bool(ended)

        except Exception:
            return False

    # Salvar áudio localmente convertendo os chunks base64 para um arquivo. 

    def _save_audio(self, session: BotSession) -> None:
        """
        Converte os chunks base64 (webm/opus) para arquivo .wav.
        Usa ffmpeg se disponível, caso contrário salva como .webm.
        """
        if not session.audio_chunks:
            print("[Bot]  Nenhum chunk de áudio coletado")
            return

        import base64
        import subprocess

        if session.output_path is None:
            print("[Bot]  Caminho de saída não definido")
            return

        # Salva chunks como .webm temporário
        webm_path = session.output_path.with_suffix(".webm")
        with open(webm_path, "wb") as file_handle:
            for chunk in session.audio_chunks:
                # Remove o prefixo data:audio/webm;base64,
                if "," in chunk:
                    chunk = chunk.split(",", 1)[1]
                file_handle.write(base64.b64decode(chunk))

        # Converte para .wav com ffmpeg se disponivel, caso contrario mentém 
        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-i",
                    str(webm_path),
                    "-ar",
                    "16000",  # 16kHz — ideal para Whisper
                    "-ac",
                    "1",  # mono
                    "-y",  # sobrescreve sem perguntar
                    str(session.output_path),
                ],
                capture_output=True,
                timeout=120,
            )
            if result.returncode == 0:
                os.remove(webm_path)
                print(f"[Bot]  Áudio salvo: {session.output_path}")
            else:
                # ffmpeg falhou — mantém o .webm
                session.output_path = webm_path
                print(f"[Bot]  Áudio salvo (webm): {webm_path}")
        except (FileNotFoundError, Exception):
            # ffmpeg não instalado — mantém o .webm
            session.output_path = webm_path
            print(f"[Bot] Áudio salvo (webm): {webm_path}")
            print("[Bot] Instale ffmpeg para converter para .wav automaticamente")

