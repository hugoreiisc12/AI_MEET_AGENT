# Implementação de ciclo de vida do BOT:
# Fluxo inicial: Rodar on setup de autenticação, Inetgração com 3 arquivos mapeadoes, 
#  A reunnião valida o processo ( dentro don time de 30 minutos da semana )
# Calibração interna de 30min 

""" Três camadas:
 
  CAMADA 1 — Unitários (rodam SEMPRE, sem navegador):
    FakePage simula o Playwright e valida toda a lógica do recorder —
    verificação de login, contagem de participantes, os 3 sinais de fim
    de reunião, espera por tracks, coleta/salvamento do áudio, entrega
    via callback e a máquina de status persistida em JSON.
 
  CAMADA 2 — Smoke test do audio_capture.js (roda se Node estiver
    instalado): valida os patches do bootstrap (RTC, srcObject), a fila
    de tracks, o dedupe e o filtro de kind — sem abrir navegador.
 
  CAMADA 3 — Teste VIVO (opcional, gated por variável de ambiente):
    entra numa sala real do Meet e valida o ciclo completo."""


from __future__ import annotations 

import asyncio
import base64
import os 
import json 
import shutil
import subprocess 
import time 
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

import pytest 

pytest.importorskip("playwright", reason="Playwright não instalado, pulando ")

from infrastructure.recorder.playwright_bot_recorder import (
    AUDIO_CAPTURE_JS,
    BotNotLoggedInError,
    BotSession,
    MEET_STATUS_JS,
    PlaywrightBotRecorder,
)

JS_PATH = (
    Path(__file__).resolve().parents[1]
    / "infrastructure" / "recorder" / "audio_capture.js"
)
 
 
def run(coro):
    """ Executa corrotinas em testes sincronos (  sem depender dpo pytest-asyncio) """

    return asyncio.run(coro)

# Duble de Playwright 
class FakeLocator:
    def __init__(self, count: int = 0, visible: bool = False,
                 aria_label: str | None = None):
        self._count = count
        self._visible = visible
        self._aria = aria_label

    @property
    def first(self):
        return self

    async def count(self) -> int:
        return self._count

    async def is_visible(self) -> bool:
        return self._visible

    async def get_attribute(self, name: str):
        return self._aria

    async def wait_for(self, **kwargs):
        return None

    async def click(self, **kwargs):
        return None

class FakePage:
    """ Simula a superfície do Page usada pelo recorder.

    - url: controla o cenário de login
    - ended_visible: tela de encerramento presente?
    - participant_label: aria-label do botão Pessoas (None = inexistente)
    - eval_map: respostas para page.evaluate por trecho do script
    """

    def __init__(self, url: str = "https://meet.google.com/zqy-foqk-rnm",
                 login_btn_visible: bool = False,
                 ended_visible: bool = False,
                 participant_label: str | None = None,
                 eval_map: dict | None = None):
        self.url = url
        self.login_btn_visible = login_btn_visible
        self.ended_visible = ended_visible
        self.participant_label = participant_label
        self.eval_map = eval_map or {}
        self.evaluated: list[str] = []

    def locator(self, selector: str) -> FakeLocator:
        sel = selector.lower()
        if "fazer login" in sel or "sign in" in sel:
            return FakeLocator(count=1 if self.login_btn_visible else 0,
                                visible=self.login_btn_visible)
        if "saiu" in sel or "encerrada" in sel or "left the call" in sel:
            return FakeLocator(count=1 if self.ended_visible else 0,
                                visible=self.ended_visible)
        if "articipante" in sel or "essoas" in sel or "people" in sel:
            if self.participant_label is None:
                return FakeLocator(count=0)
            return FakeLocator(count=1, aria_label=self.participant_label)
        return FakeLocator(count=0)

    async def evaluate(self, script: str):
        self.evaluated.append(script)
        for key, value in sorted(self.eval_map.items(), key=lambda x: len(x[0]), reverse=True):
            if key in script:
                return value() if callable(value) else value
        raise AssertionError(f"evaluate inesperado no teste: {script[:80]}...")
 
 
@pytest.fixture
def recorder(tmp_path) -> PlaywrightBotRecorder:
    r = PlaywrightBotRecorder(
        chrome_profile_dir=tmp_path / "profile",
        audio_dir=tmp_path / "audio",
        headless=True,
    )
    r.session = BotSession(meeting_url="https://meet.google.com/zqy-foqk-rnm")
    return r
 
 
# ======================================================================
# Unitários
# ======================================================================
class TestVerificacaoDeLogin:
    def test_redirect_para_accounts_levanta_erro_acionavel(self, recorder):
        page = FakePage(url="https://accounts.google.com/signin")
        with pytest.raises(BotNotLoggedInError, match="bot_setup"):
            run(recorder._verify_logged_in(page))
 
    def test_botao_fazer_login_visivel_levanta_erro(self, recorder):
        page = FakePage(login_btn_visible=True)
        with pytest.raises(BotNotLoggedInError):
            run(recorder._verify_logged_in(page))
 
    def test_sessao_valida_passa_sem_erro(self, recorder):
        run(recorder._verify_logged_in(FakePage()))
 
 
class TestContagemDeParticipantes:
    def test_snapshot_extrai_participantes(self, recorder):
        page = FakePage(eval_map={
            MEET_STATUS_JS: {"participants": 4, "speaking": [], "recording": False,
                             "audioChunks": 0, "lastAudioTs": 0, "captureError": None},
        })
        snap = run(recorder._get_status_snapshot(page))
        assert snap["participants"] == 4

    def test_sem_botao_retorna_indeterminado(self, recorder):
        page = FakePage(eval_map={
            MEET_STATUS_JS: {"participants": -1, "speaking": [], "recording": False,
                             "audioChunks": 0, "lastAudioTs": 0, "captureError": None},
        })
        snap = run(recorder._get_status_snapshot(page))
        assert snap["participants"] == -1

    def test_label_sem_numero_retorna_indeterminado(self, recorder):
        page = FakePage(eval_map={
            MEET_STATUS_JS: {"participants": -1, "speaking": [], "recording": False,
                             "audioChunks": 0, "lastAudioTs": 0, "captureError": None},
        })
        snap = run(recorder._get_status_snapshot(page))
        assert snap["participants"] == -1
 
 
class TestFimDeReuniao:
    """Os 3 sinais combinados — nenhum encerra por engano, todos encerram
    quando devem. POLL_INTERVAL reduzido para o teste ser instantâneo."""
 
    @pytest.fixture(autouse=True)
    def _rapido(self, monkeypatch):
        monkeypatch.setattr(PlaywrightBotRecorder, "POLL_INTERVAL", 0.01)
 
    def _snapshot(self, participants=0, last_audio_ts=None):
        agora = int(time.time() * 1000)
        return {
            MEET_STATUS_JS: {
                "participants": participants,
                "speaking": [],
                "recording": True,
                "audioChunks": 5,
                "lastAudioTs": last_audio_ts or agora,
                "captureError": None,
            },
        }

    def test_sinal_1_tela_de_encerramento(self, recorder):
        page = FakePage(ended_visible=True, eval_map=self._snapshot())
        run(asyncio.wait_for(recorder._wait_until_meeting_ends(page), timeout=2))

    def test_sinal_2_sozinho_na_sala_apos_timeout(self, recorder, monkeypatch):
        monkeypatch.setattr(PlaywrightBotRecorder, "ALONE_TIMEOUT", 0.005)
        page = FakePage(eval_map=self._snapshot(participants=1))
        run(asyncio.wait_for(recorder._wait_until_meeting_ends(page), timeout=2))

    def test_sinal_3_silencio_prolongado(self, recorder, monkeypatch):
        monkeypatch.setattr(PlaywrightBotRecorder, "SILENCE_TIMEOUT", 10)
        antigo = int((time.time() - 3600) * 1000)  # último áudio há 1 hora
        page = FakePage(eval_map=self._snapshot(participants=3, last_audio_ts=antigo))
        run(asyncio.wait_for(recorder._wait_until_meeting_ends(page), timeout=2))

    def test_reuniao_ativa_nao_encerra(self, recorder, monkeypatch):
        """3 participantes, com áudio, sem tela de fim => continua rodando."""
        monkeypatch.setattr(PlaywrightBotRecorder, "ALONE_TIMEOUT", 0.005)
        monkeypatch.setattr(PlaywrightBotRecorder, "POLL_INTERVAL", 0.01)
        page = FakePage(eval_map=self._snapshot(participants=3))
        with pytest.raises(asyncio.TimeoutError):
            run(asyncio.wait_for(recorder._wait_until_meeting_ends(page),
                                 timeout=0.2))
 
 
class TestInicioDaCaptura:
    def test_recorder_ativo_com_track_retorna(self, recorder):
        page = FakePage(eval_map={
            AUDIO_CAPTURE_JS: None,
            "window.__meetCapture._resume()": None,
            "window.__meetCapture.getState()": {
                "recording": True, "audioTracks": 1,
                "sources": {"rtc": 1, "srcObject": 0, "dom": 0},
            },
            "window.__meetCapture._error": None,
        })
        run(recorder._inject_audio_capture(page))

    def test_mediarecorder_morto_levanta_erro(self, recorder):
        page = FakePage(eval_map={
            AUDIO_CAPTURE_JS: None,
            "window.__meetCapture._resume()": None,
            "window.__meetCapture.getState()": {
                "recording": False, "audioContextState": "suspended",
            },
            "window.__meetCapture._error": "MediaRecorder falhou",
        })
        with pytest.raises(RuntimeError, match="MediaRecorder"):
            run(recorder._inject_audio_capture(page))

    def test_sala_vazia_avisa_mas_nao_aborta(self, recorder):
        page = FakePage(eval_map={
            AUDIO_CAPTURE_JS: None,
            "window.__meetCapture._resume()": None,
            "window.__meetCapture.getState()": {
                "recording": True, "audioTracks": 0, "sources": {},
            },
            "window.__meetCapture._error": None,
        })
        run(recorder._inject_audio_capture(page))  # não levanta exceção
 
 
class TestColetaEEntrega:
    def test_salva_webm_e_speakers_json(self, recorder):
        conteudo = b"\x1aE\xdf\xa3fake-webm-bytes"
        log = [{"t": 1.5, "rms": 0.04, "speakers": ["Hugo"]}]
        page = FakePage(eval_map={
            "window.__meetCapture.stop()": base64.b64encode(conteudo).decode(),
            "window.__meetCapture.getSpeakerLog()": log,
        })
        run(recorder._collect_and_save_audio(page))

        assert recorder.session.audio_path.read_bytes() == conteudo
        salvo = json.loads(recorder.session.speaker_log_path.read_text(
            encoding="utf-8"))
        assert salvo == log
 
    def test_callback_de_entrega_recebe_os_paths(self, recorder, tmp_path):
        recebido = {}
 
        async def on_ready(audio_path, log_path):
            recebido["audio"] = audio_path
            recebido["log"] = log_path
 
        recorder.on_audio_ready = on_ready
        recorder.session.audio_path = tmp_path / "a.webm"
        recorder.session.speaker_log_path = tmp_path / "a.speakers.json"
        run(recorder._deliver())
        assert recebido["audio"] == recorder.session.audio_path
 
    def test_modo_solo_sem_callback_nao_quebra(self, recorder, tmp_path):
        recorder.on_audio_ready = None
        recorder.session.audio_path = tmp_path / "a.webm"
        run(recorder._deliver())
 
 
class TestMaquinaDeStatus:
    def test_transicao_persiste_json_legivel_pela_ui(self, recorder):
        recorder._set_status("recording")
        path = recorder.status_dir / f"bot_session_{recorder.session.id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["status"] == "recording"
        assert data["meeting_url"] == "https://meet.google.com/zqy-foqk-rnm"
        assert data["error"] is None
 
    def test_falha_registra_erro_no_json(self, recorder):
        recorder._set_status("failed", error="BotNotLoggedInError: sessão expirada")
        path = recorder.status_dir / f"bot_session_{recorder.session.id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["status"] == "failed"
        assert "sessão expirada" in data["error"]
 
 
# ======================================================================
# CAMADA 2 — Smoke test do audio_capture.js (requer Node)
# ======================================================================
NODE = shutil.which("node")
 
_JS_SMOKE = r"""
const origSetInterval = global.setInterval;
global.window = global;
global.setInterval = function(fn, ms) {
  const timer = origSetInterval(fn, ms);
  timer.unref();
  return timer;
};
global.clearInterval = clearInterval;
global.Float32Array = Float32Array;
global.AudioContext = function(){
  this.state = 'suspended';
  this.resume = ()=>{ this.state = 'running'; };
  this.createAnalyser = () => ({ fftSize: 2048, getFloatTimeDomainData: (buf) => { for (let i=0;i<buf.length;i++) buf[i]=0; } });
  this.createMediaStreamSource = () => ({ connect: () => {} });
  this.createMediaElementSource = () => ({ connect: () => {} });
  this.createMediaStreamDestination = () => ({ stream: 'fake-stream' });
};
global.MediaRecorder = function(){
  this.state = 'inactive';
  this.start = function(){ this.state = 'recording'; };
  this.stop = function(){ this.state = 'inactive'; };
};
global.Blob = function(){};
global.FileReader = function(){
  this.readAsDataURL = function(){
    this.onloadend && this.onloadend();
  };
  this.result = 'data:audio/webm;base64,dGVzdGUtYXVkaW8=';
};
Object.defineProperty(global, 'navigator', {
  value: {
    mediaDevices: {
      getDisplayMedia: () => { throw new Error('No display in Node'); },
    },
  },
  configurable: true, writable: true,
});
global.document = {
  querySelectorAll: () => [{ tagName: 'AUDIO' }],
  querySelector: () => null,
  documentElement: {},
};
global.MutationObserver = function(){
  this.observe = () => {};
  this.disconnect = () => {};
};

(async () => {
  const fs = require('fs');
  eval(fs.readFileSync(process.argv[2], 'utf8'));

  // Wait for the async init() microtask to complete
  await new Promise(r => setTimeout(r, 10));

  const assert = require('assert');
  const cap = window.__meetCapture;
  assert(cap, '__meetCapture não foi criado');
  assert.strictEqual(typeof cap.stop, 'function');
  assert.strictEqual(typeof cap.getSpeakerLog, 'function');
  assert.strictEqual(typeof cap.getLastAudioTs, 'function');
  assert.strictEqual(typeof cap.getState, 'function');
  assert.strictEqual(typeof cap._resume, 'function');
  const st = cap.getState();
  assert('recording' in st);
  assert('chunks' in st);
  console.log('OK');
})().catch(e => { console.error(e.message); process.exit(1); });
"""
 
 
@pytest.mark.skipif(NODE is None, reason="Node.js não instalado")
class TestAudioCaptureJs:
    def test_arquivo_existe_com_apis_essenciais(self):
        src = JS_PATH.read_text(encoding="utf-8")
        for api in ("window.__meetCapture", "MediaRecorder", "stop:",
                    "getSpeakerLog", "getLastAudioTs", "getState:", "_resume:"):
            assert api in src, f"API ausente no audio_capture.js: {api}"
        for api in ("readActiveSpeakers", "startMeter", "initFallback", "init"):
            assert api in src, f"Função ausente no audio_capture.js: {api}"
 
    def test_bootstrap_patches_fila_e_dedupe(self, tmp_path):
        smoke = tmp_path / "smoke.js"
        smoke.write_text(_JS_SMOKE, encoding="utf-8")
        result = subprocess.run([NODE, str(smoke), str(JS_PATH)],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        assert "OK" in result.stdout
 
 
# ======================================================================
# CAMADA 3 — Teste vivo (opcional): exige sala real e perfil logado
# ======================================================================
MEET_TEST_URL = os.environ.get("MEET_TEST_URL")
 
 
@pytest.mark.skipif(not MEET_TEST_URL,
                    reason="defina MEET_TEST_URL para o teste vivo")
class TestBotVivo:
    def test_ciclo_completo_em_sala_real(self, monkeypatch, tmp_path):
        """Entra na sala, grava e sai sozinho. Para validar ÁUDIO real,
        entre na mesma sala com uma segunda conta e fale algo."""
        monkeypatch.setattr(PlaywrightBotRecorder, "ALONE_TIMEOUT", 30)
        monkeypatch.setattr(PlaywrightBotRecorder, "JOIN_TIMEOUT", 30_000)
        profile = Path(os.environ.get("BOT_PROFILE_DIR",
                         os.environ.get("BOT_CHROME_PROFILE", "./bot_chrome_profile")))
        assert profile.exists(), (
            f"Perfil '{profile}' não existe — rode antes: "
            "python -m infrastructure.recorder.bot_setup"
        )
 
        recorder = PlaywrightBotRecorder(
            chrome_profile_dir=profile,
            audio_dir=tmp_path,
            headless=os.environ.get("BOT_HEADLESS", "0") == "1",
        )
        session = run(recorder.join_async(MEET_TEST_URL))
 
        assert session.status == "done"
        assert session.audio_path and session.audio_path.exists()
        assert session.audio_path.stat().st_size > 0, "webm vazio"
        assert session.speaker_log_path.exists()
        print(f"\nÁudio: {session.audio_path} "
              f"({session.audio_path.stat().st_size/1024:.1f} KB) — OUÇA-O.)")