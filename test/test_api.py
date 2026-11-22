"""API: autenticação, limites e sessão de captura (ADR-007)."""
import io
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.security import capture_token
from domain.entities.meeting import Meeting, MeetingStatus
from infrastructure.json_meeting_repository import JsonMeetingRepository

from presentation.container import Container
from use_cases.auth import AuthService

KEY = "chave-de-teste"
LINK_LOCK = threading.Lock()
AUTH = {"X-API-Key": KEY}


class MemoryAuthStore:
    """Mesmo contrato do MongoAuthStore, em memória."""

    def __init__(self):
        self.users, self.sessions_, self.resets = {}, {}, {}

    def add_user(self, user):
        if any(u.email == user.email for u in self.users.values()):
            return False
        self.users[user.id] = user
        return True

    def user_by_email(self, email):
        return next((u for u in self.users.values() if u.email == email), None)

    def user_by_id(self, user_id):
        return self.users.get(user_id)

    def list_users(self):
        return list(self.users.values())

    def count_users(self):
        return len(self.users)

    def update_user(self, user_id, fields):
        for k, v in fields.items():
            setattr(self.users[user_id], k, v)

    def add_session(self, session):
        self.sessions_[session["_id"]] = session

    def session(self, sid):
        return self.sessions_.get(sid)

    def sessions_of(self, user_id):
        return [s for s in self.sessions_.values() if s["user_id"] == user_id]

    def delete_session(self, sid):
        self.sessions_.pop(sid, None)

    def delete_sessions(self, user_id=None, keep=None, expired_before=None):
        doomed = [sid for sid, s in self.sessions_.items()
                  if (user_id is None or s["user_id"] == user_id) and sid != keep
                  and (expired_before is None or s["expires_at"] < expired_before)]
        for sid in doomed:
            del self.sessions_[sid]
        return len(doomed)

    def put_reset(self, reset):
        self.resets[reset["_id"]] = dict(reset)

    def get_reset(self, user_id):
        return self.resets.get(user_id)

    def update_reset(self, user_id, fields):
        self.resets[user_id].update(fields)

    def delete_reset(self, user_id):
        self.resets.pop(user_id, None)


class FakeContainer:
    """Container sem fila nem LLM; as regras de dono e de envio do bot são as de verdade."""
    meeting_for = Container.meeting_for
    meetings_of = Container.meetings_of
    _follow = Container._follow
    delete_meeting = Container.delete_meeting
    register_user = Container.register_user
    set_task_done = Container.set_task_done
    dispatch_bot = Container.dispatch_bot
    send_password_reset = Container.send_password_reset
    _title_from_calendar = Container._title_from_calendar
    queue_position = Container.queue_position
    progress = Container.progress
    resume = Container.resume
    clear_chat = Container.clear_chat
    bot_status = Container.bot_status
    request_bot_setup = Container.request_bot_setup
    indexer = None  # sem memória do agente
    _bot_worker_alive = staticmethod(lambda: True)  # batimento do bot: os testes que precisam desligam
    bot_account = None  # sem credenciamento (como em solo); os testes do bot ligam um store
    auth = None
    _link_lock = staticmethod(lambda key: LINK_LOCK)  # em vez do Redis  # como em solo; os testes de login ligam com `with_login`
    calendar = None
    _is_collab = True

    def __init__(self, repo, queued):
        self.repository, self.queued = repo, queued
        self.documents_dir = Path(repo._base).parent / "documents"
        from infrastructure.memory_store import JsonMemoryStore
        self.memory = JsonMemoryStore(str(Path(repo._base).parent / "memories.json"))

    def enqueue_processing(self, meeting_id, audio_path, title, wait=False, owner_id=""):
        self.queued.append((meeting_id, audio_path, title))
        self.repository.save(Meeting(id=meeting_id, title=title, owner_id=owner_id, audio_path=audio_path))


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    settings = SimpleNamespace(
        api_key=KEY, audio_storage_path=str(tmp_path / "audio"), max_upload_mb=1,
        capture_max_chunk_mb=1, capture_max_session_mb=2, app_mode="solo",
        rate_limit_per_minute=0, is_collab=False,
    )
    repo = JsonMeetingRepository(str(tmp_path / "meetings"))
    queued = []
    container = FakeContainer(repo, queued)
    import api.main as main
    for mod in ("api.security", "api.routers.capture", "api.routers.meetings"):
        monkeypatch.setattr(f"{mod}.get_settings", lambda: settings)
    for mod in ("api.security", "api.routers.auth", "api.routers.bot", "api.routers.capture", "api.routers.meetings",
                "api.routers.memory", "api.routers.observability", "api.routers.calendar", "api.chat"):
        monkeypatch.setattr(f"{mod}.get_container", lambda: container)
    import worker.tasks
    bots = []
    monkeypatch.setattr(worker.tasks.join_meeting_task, "delay", lambda *a: bots.append(a))
    container.bots = bots
    return SimpleNamespace(client=TestClient(main.app), repo=repo, queued=queued, settings=settings,
                           tmp=tmp_path, container=container)


def test_rotas_exigem_chave_e_health_nao(ctx):
    assert ctx.client.get("/health").status_code != 401
    assert ctx.client.get("/meetings/").status_code == 401
    assert ctx.client.get("/meetings/", headers={"X-API-Key": "errada"}).status_code == 401
    assert ctx.client.post("/meetings/x/chat", json={"question": "oi"}).status_code == 401
    assert ctx.client.get("/meetings/", headers=AUTH).status_code == 200


def test_upload_grava_em_disco_e_enfileira(ctx):
    r = ctx.client.post("/meetings/upload", headers=AUTH, files={"file": ("a.wav", io.BytesIO(b"x" * 10))})
    assert r.status_code == 200 and len(ctx.queued) == 1
    assert (ctx.tmp / "audio" / f"{r.json()['meeting_id']}.wav").read_bytes() == b"x" * 10


def test_upload_acima_do_teto_devolve_413_e_nao_deixa_arquivo(ctx):
    big = io.BytesIO(b"x" * (1024 * 1024 + 1))
    r = ctx.client.post("/meetings/upload", headers=AUTH, files={"file": ("a.wav", big)})
    assert r.status_code == 413 and not ctx.queued
    assert list((ctx.tmp / "audio").glob("*")) == []


def test_upload_recusa_extensao_estranha_e_arquivo_vazio(ctx):
    assert ctx.client.post("/meetings/upload", headers=AUTH, files={"file": ("a.sh", b"x")}).status_code == 415
    assert ctx.client.post("/meetings/upload", headers=AUTH, files={"file": ("a.wav", b"")}).status_code == 422


def test_live_devolve_parcial_so_durante_a_transcricao(ctx):
    from domain.entities.meeting import MeetingStatus
    from infrastructure.transcriber.live_transcript import PartialWriter
    audio = ctx.tmp / "audio" / "m9.webm"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"x")
    w = PartialWriter(str(audio))
    w.append(0.0, 1.2, "bom dia")
    w.close()
    ctx.repo.save(Meeting(id="m9", title="t", audio_path=str(audio), status=MeetingStatus.TRANSCRIBING))
    r = ctx.client.get("/meetings/m9/live", headers=AUTH).json()
    assert r["status"] == "transcribing" and [s["text"] for s in r["segments"]] == ["bom dia"]

    ctx.repo.save(Meeting(id="m9", title="t", audio_path=str(audio), status=MeetingStatus.SUMMARIZING))
    assert ctx.client.get("/meetings/m9/live", headers=AUTH).json()["segments"] == []
    assert ctx.client.get("/meetings/nada/live", headers=AUTH).status_code == 404


def chunk(ctx, session="m1", data=b"abc", token=None):
    token = capture_token(session, KEY) if token is None else token
    return ctx.client.post(f"/capture/chunk?session={session}&seq=0", content=data, headers={"X-Capture-Token": token})


def test_captura_exige_token_da_propria_sessao(ctx):
    ctx.repo.save(Meeting(id="m1", title="t"))
    assert chunk(ctx, token="").status_code == 401
    assert chunk(ctx, token=capture_token("outra", KEY)).status_code == 401
    assert chunk(ctx, token=KEY).status_code == 401  # a chave da API não serve de token
    assert chunk(ctx).status_code == 200
    assert (ctx.tmp / "audio" / "m1.webm").read_bytes() == b"abc"


def test_captura_so_aceita_reuniao_existente_e_aberta(ctx):
    assert chunk(ctx, session="fantasma").status_code == 404
    ctx.repo.save(Meeting(id="m1", title="t", status=MeetingStatus.RECORDING))
    assert chunk(ctx).status_code == 200
    ctx.repo.save(Meeting(id="m1", title="t", status=MeetingStatus.TRANSCRIBING))
    assert chunk(ctx).status_code == 409
    status = ctx.client.get("/capture/status?session=m1", headers={"X-Capture-Token": capture_token("m1", KEY)})
    assert status.json()["finalized"] is True


def test_captura_limita_chunk_e_sessao(ctx):
    ctx.repo.save(Meeting(id="m1", title="t"))
    mb = b"x" * (1024 * 1024)
    assert chunk(ctx, data=mb + b"x").status_code == 413          # chunk acima de 1 MB
    assert chunk(ctx, data=mb).status_code == 200
    assert chunk(ctx, data=mb).status_code == 200
    assert chunk(ctx, data=b"x").status_code == 413               # sessão acima de 2 MB
    assert chunk(ctx, session="../m1").status_code in (400, 401)


def test_sem_chave_configurada_a_api_fica_aberta_em_desenvolvimento(ctx):
    ctx.settings.api_key = ""
    assert ctx.client.get("/meetings/").status_code == 200


def test_log_carrega_o_id_da_reuniao(capsys):
    import logging
    from config.logging_setup import bind_meeting, setup_logging
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    try:
        setup_logging()
        bind_meeting("abc-123")
        logging.getLogger("qualquer.lib").info("mensagem")
        assert "[abc-123] qualquer.lib: mensagem" in capsys.readouterr().err
    finally:
        root.handlers, _ = saved[0], root.setLevel(saved[1])
        bind_meeting("-")


# ── Sprint 4: tarefas, exportação, e-mail, agenda ────────────────────────

def _meeting_with_tasks(ctx):
    from domain.entities.meeting import Summary, Task
    m = Meeting(id="m1", title="Planejamento", transcript_text="Ana: oi", participants=["Ana"],
                summary=Summary(overview="geral", tasks=[Task("Revisar fluxo", "Ana", "sexta"), Task("Planejar QA")]),
                status=MeetingStatus.DONE)
    ctx.repo.save(m)
    return m


def test_marcar_tarefa_sobrevive_a_recarregar(ctx, monkeypatch):
    _meeting_with_tasks(ctx)
    r = ctx.client.patch("/meetings/m1/tasks/1", headers=AUTH, json={"done": True})
    assert r.status_code == 200 and [t["done"] for t in r.json()["summary"]["tasks"]] == [False, True]
    assert [t.done for t in ctx.repo.find_by_id("m1").summary.tasks] == [False, True]
    assert ctx.client.patch("/meetings/m1/tasks/9", headers=AUTH, json={"done": True}).status_code == 404
    assert ctx.client.patch("/meetings/nada/tasks/0", headers=AUTH, json={"done": True}).status_code == 404


def test_exportacao_markdown(ctx):
    _meeting_with_tasks(ctx)
    r = ctx.client.get("/meetings/m1/export.md", headers=AUTH)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown")
    assert "# Planejamento" in r.text and "- [ ] **Revisar fluxo** — Ana (sexta)" in r.text and "Ana: oi" in r.text


def test_email_de_tarefas(ctx, monkeypatch):
    import infrastructure.email.email_sender as mod
    _meeting_with_tasks(ctx)
    sent = []

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, context=None): pass
        def auth_plain(self): return ""
        def auth(self, mechanism, authobject): sent.append(("login", self.user))
        def sendmail(self, frm, to, body): sent.append((frm, to, body))

    smtp = SimpleNamespace(smtp_user="", smtp_password="", smtp_from_email="", smtp_host="h", smtp_port=1, email_enabled=False)
    monkeypatch.setattr(mod, "get_settings", lambda: smtp)
    monkeypatch.setattr(mod.smtplib, "SMTP", FakeSMTP)

    # sem SMTP configurado: recusa com mensagem clara, não tenta enviar
    r = ctx.client.post("/meetings/m1/tasks/email", headers=AUTH, json={"to": "ana@empresa.com"})
    assert r.status_code == 409 and "SMTP" in r.json()["detail"] and not sent

    smtp.smtp_user, smtp.smtp_password, smtp.email_enabled = "bot@empresa.com", "segredo", True
    assert ctx.client.post("/meetings/m1/tasks/email", headers=AUTH, json={"to": "nao-e-email"}).status_code == 422
    r = ctx.client.post("/meetings/m1/tasks/email", headers=AUTH, json={"to": "ana@empresa.com"})
    assert r.status_code == 200 and sent[1][:2] == ("bot@empresa.com", "ana@empresa.com")
    import email
    body = email.message_from_string(sent[1][2]).get_payload()[0].get_payload(decode=True).decode()
    assert "Revisar fluxo — responsável: Ana — prazo: sexta" in body and "Planejar QA" in body


def test_agenda_da_titulo_ao_bot_e_falha_da_agenda_nao_impede(tmp_path):
    from presentation.container import Container
    from infrastructure.json_meeting_repository import JsonMeetingRepository

    class Cal:
        def __init__(self, title=None, boom=False): self.title, self.boom = title, boom
        def find_by_meet_url(self, url):
            if self.boom:
                raise RuntimeError("sem token")
            return SimpleNamespace(title=self.title) if self.title else None

    c = Container.__new__(Container)
    c.repository, c._is_collab = JsonMeetingRepository(str(tmp_path)), True
    c._link_lock = lambda key: LINK_LOCK
    c.bot_account = None
    import worker.tasks as tasks
    dispatched = []
    orig = tasks.join_meeting_task.delay
    tasks.join_meeting_task.delay = lambda *a: dispatched.append(a)
    try:
        url = "https://meet.google.com/abc-defg-hi{}"
        c.calendar = Cal("Sprint Review")
        assert c.repository.find_by_id(c.dispatch_bot(url.format("a"))).title == "Sprint Review"
        assert c.repository.find_by_id(c.dispatch_bot(url.format("b"), "Meu título")).title == "Meu título"
        c.calendar = Cal(boom=True)
        assert c.repository.find_by_id(c.dispatch_bot(url.format("c"))).title.startswith("Reunião ")
        c.calendar = None
        assert c.repository.find_by_id(c.dispatch_bot(url.format("d"))).title.startswith("Reunião ")
        assert len(dispatched) == 4
    finally:
        tasks.join_meeting_task.delay = orig


# ── Sprint 5: login multiusuário, plataformas e contrato da API ──────────

@pytest.fixture
def with_login(ctx):
    ctx.store = MemoryAuthStore()
    ctx.container.auth = AuthService(ctx.store)
    return ctx


def signup(ctx, email="ana@empresa.com", name="Ana", password="senha-forte"):
    r = ctx.client.post("/auth/register", json={"name": name, "email": email, "password": password})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["user"]


def test_cadastro_login_e_logout(with_login):
    c = with_login.client
    ana, user = signup(with_login, email="Ana@Empresa.com")
    assert user["email"] == "ana@empresa.com" and "password" not in str(user)
    assert c.get("/auth/me", headers=ana).json()["name"] == "Ana"

    assert c.post("/auth/register", json={"name": "X", "email": "ana@empresa.com", "password": "outra-senha"}).status_code == 409
    assert c.post("/auth/register", json={"name": "X", "email": "x@y.com", "password": "curta"}).status_code == 422
    assert c.post("/auth/register", json={"name": "X", "email": "sem-arroba", "password": "senha-forte"}).status_code == 409

    assert c.post("/auth/login", json={"email": "ana@empresa.com", "password": "errada-mesmo"}).status_code == 401
    assert c.post("/auth/login", json={"email": "ninguem@x.com", "password": "senha-forte"}).status_code == 401
    r = c.post("/auth/login", json={"email": "ANA@empresa.com", "password": "senha-forte"})
    outra = {"Authorization": f"Bearer {r.json()['token']}"}
    assert r.status_code == 200 and c.get("/auth/me", headers=outra).status_code == 200

    assert c.post("/auth/logout", headers=outra).status_code == 204
    assert c.get("/auth/me", headers=outra).status_code == 401      # sessão encerrada
    assert c.get("/auth/me", headers=ana).status_code == 200        # a outra sessão continua
    assert c.get("/auth/me", headers=AUTH).status_code == 401       # chave de serviço não é usuário


def test_banco_nao_guarda_senha_nem_token(with_login):
    ana, _ = signup(with_login)
    token = ana["Authorization"].split()[1]
    stored = str(vars(next(iter(with_login.store.users.values())))) + str(with_login.store.sessions_)
    assert "senha-forte" not in stored and token not in stored


def test_sessao_vencida_e_recusada(with_login):
    from datetime import datetime, timedelta
    ana, _ = signup(with_login)
    for s in with_login.store.sessions_.values():
        s["expires_at"] = datetime.now() - timedelta(days=1)
    assert with_login.client.get("/meetings/", headers=ana).status_code == 401


def test_cada_usuario_ve_so_as_proprias_reunioes(with_login):
    c = with_login.client
    with_login.repo.save(Meeting(id="antiga", title="Antes do login", transcript_text="oi"))
    ana, ana_user = signup(with_login)
    bia, _ = signup(with_login, email="bia@empresa.com", name="Bia")

    # a primeira conta herda o que existia; a segunda começa vazia
    assert [m["meeting_id"] for m in c.get("/meetings/", headers=ana).json()] == ["antiga"]
    assert c.get("/meetings/", headers=bia).json() == []

    r = c.post("/meetings/bot", headers=bia, json={"meeting_url": "https://meet.google.com/abc-defg-hij", "title": "Da Bia"})
    bia_id = r.json()["meeting_id"]
    assert r.status_code == 200 and with_login.repo.find_by_id(bia_id).platform == "meet"
    assert [m["title"] for m in c.get("/meetings/", headers=bia).json()] == ["Da Bia"]

    # reunião alheia responde 404 em toda rota, sem revelar que existe
    for method, path, body in [
        ("get", "/meetings/{id}", None), ("get", "/meetings/{id}/status", None),
        ("get", "/meetings/{id}/live", None),
        ("get", "/meetings/{id}/export.md", None), ("delete", "/meetings/{id}", None),
        ("post", "/meetings/{id}/process", None), ("post", "/meetings/{id}/chat", {"question": "oi"}),
        ("post", "/meetings/{id}/chat/stream", {"question": "oi"}),
        ("patch", "/meetings/{id}/tasks/0", {"done": True}),
        ("post", "/meetings/{id}/tasks/email", {"to": "a@b.com"}),
    ]:
        assert c.request(method, path.format(id=bia_id), headers=ana, json=body).status_code == 404, path
    assert with_login.repo.find_by_id(bia_id) is not None

    assert len(c.get("/meetings/", headers=AUTH).json()) == 2       # chave de serviço enxerga tudo
    assert c.get("/meetings/").status_code == 401


def test_detalhe_e_exclusao(with_login):
    c = with_login.client
    ana, user = signup(with_login)
    audio = with_login.tmp / "audio" / "m1.webm"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"x")
    with_login.repo.save(Meeting(
        id="m1", title="T", owner_id=user["id"], audio_path=str(audio), transcript_formatted="[00:00] Ana: oi",
        status=MeetingStatus.DONE,
    ))
    with_login.repo.append_chat("m1", [{"role": "user", "content": "quem falou?"}, {"role": "assistant", "content": "Ana"}])
    d = c.get("/meetings/m1", headers=ana).json()
    assert d["transcript"] == "[00:00] Ana: oi" and d["has_audio"] and d["chat_history"][1]["content"] == "Ana"
    assert c.delete("/meetings/m1", headers=ana).status_code == 204
    assert with_login.repo.find_by_id("m1") is None and not audio.exists()


def test_links_de_reuniao_aceitos():
    from infrastructure.recorder.platforms import UnsupportedMeetingUrl, detect_platform
    assert detect_platform("https://meet.google.com/abc-defg-hij").key == "meet"
    assert detect_platform("https://teams.microsoft.com/l/meetup-join/19%3ameeting").key == "teams"
    zoom = detect_platform("https://us02web.zoom.us/j/12345678901?pwd=abc")
    assert zoom.join_url("https://us02web.zoom.us/j/12345678901?pwd=abc") == "https://app.zoom.us/wc/12345678901/join?pwd=abc"
    for bad in ("http://meet.google.com/abc", "https://evil.com/meet.google.com", "https://notzoom.us/j/12345678901",
                "https://zoom.us/my/sala", "https://discord.com/channels/1/2", "", "javascript:alert(1)"):
        with pytest.raises(UnsupportedMeetingUrl):
            detect_platform(bad)


def test_config_publica_lista_plataformas(ctx):
    r = ctx.client.get("/config")
    assert r.status_code == 200 and [p["key"] for p in r.json()["platforms"]] == ["meet", "teams", "zoom"]
    assert ctx.client.post("/meetings/bot", headers=AUTH, json={"meeting_url": "https://discord.com/channels/1/2"}).status_code == 422


def test_openapi_em_dia():
    """docs/api/openapi.json é o contrato do front: regenere com `python -m api.export_openapi`."""
    import json
    from api.export_openapi import PATH, render

    def shape(spec):  # rotas e modelos; o texto exato varia com a versão do FastAPI
        return ({(p, m) for p, ops in spec["paths"].items() for m in ops}, set(spec["components"]["schemas"]))

    assert shape(json.loads(PATH.read_text(encoding="utf-8"))) == shape(json.loads(render()))


# ── Sprint 7: sessões, bloqueio, senha, admin e isolamento por perfil ────

def test_minhas_sessoes_encerrar_uma_e_todas_as_outras(with_login):
    c = with_login.client
    ana, _ = signup(with_login)
    tok = lambda r: {"Authorization": f"Bearer {r.json()['token']}"}
    celular = tok(c.post("/auth/login", json={"email": "ana@empresa.com", "password": "senha-forte"}))
    notebook = tok(c.post("/auth/login", json={"email": "ana@empresa.com", "password": "senha-forte"}))
    bia, _ = signup(with_login, email="bia@empresa.com", name="Bia")

    lista = c.get("/auth/sessions", headers=ana).json()
    assert len(lista) == 3 and sum(s["current"] for s in lista) == 1
    assert not any(ana["Authorization"].split()[1] in str(s) for s in lista)  # token nunca aparece

    # sessão de outro usuário: 404, e continua valendo
    bia_sid = c.get("/auth/sessions", headers=bia).json()[0]["id"]
    assert c.delete(f"/auth/sessions/{bia_sid}", headers=ana).status_code == 404
    assert c.get("/auth/me", headers=bia).status_code == 200

    alvo = next(s["id"] for s in lista if not s["current"])
    assert c.delete(f"/auth/sessions/{alvo}", headers=ana).status_code == 204
    assert c.delete("/auth/sessions", headers=ana).json() == {"count": 1}
    assert [c.get("/auth/me", headers=h).status_code for h in (ana, celular, notebook, bia)] == [200, 401, 401, 200]


def test_cinco_senhas_erradas_bloqueiam(with_login, monkeypatch):
    import use_cases.auth as auth
    c = with_login.client
    signup(with_login)
    errada = {"email": "ana@empresa.com", "password": "errada-123"}
    assert [c.post("/auth/login", json=errada).status_code for _ in range(5)] == [401] * 5
    certa = {"email": "ana@empresa.com", "password": "senha-forte"}
    r = c.post("/auth/login", json=certa)
    assert r.status_code == 429 and "bloqueada" in r.json()["detail"]
    later = auth.utcnow() + auth.timedelta(minutes=auth.LOCK_MINUTES + 1)
    monkeypatch.setattr(auth, "utcnow", lambda: later)
    assert c.post("/auth/login", json=certa).status_code == 200
    assert with_login.store.user_by_email("ana@empresa.com").failed_logins == 0


def test_trocar_senha_encerra_as_outras_sessoes(with_login):
    c = with_login.client
    ana, _ = signup(with_login)
    outra = {"Authorization": "Bearer " + c.post("/auth/login", json={"email": "ana@empresa.com", "password": "senha-forte"}).json()["token"]}
    assert c.post("/auth/password", headers=ana, json={"current_password": "errada!!", "new_password": "nova-senha"}).status_code == 400
    assert c.post("/auth/password", headers=ana, json={"current_password": "senha-forte", "new_password": "nova-senha"}).json() == {"count": 1}
    assert c.get("/auth/me", headers=ana).status_code == 200 and c.get("/auth/me", headers=outra).status_code == 401
    assert c.post("/auth/login", json={"email": "ana@empresa.com", "password": "nova-senha"}).status_code == 200


def test_recuperar_senha_por_codigo(with_login, monkeypatch):
    import infrastructure.email.email_sender as mail
    c = with_login.client
    ana, _ = signup(with_login)
    sent = []
    monkeypatch.setattr(mail.EmailSender, "__init__", lambda self: None)
    monkeypatch.setattr(mail.EmailSender, "send_password_reset", lambda self, to, name, code, minutes: sent.append((to, code)))
    monkeypatch.setattr("presentation.container.get_settings", lambda: SimpleNamespace(email_enabled=True))

    # mesma resposta para e-mail com e sem conta; só a conta real recebe código
    assert c.post("/auth/password/forgot", json={"email": "ninguem@x.com"}).status_code == 202
    assert c.post("/auth/password/forgot", json={"email": "ANA@empresa.com"}).status_code == 202
    assert len(sent) == 1 and sent[0][0] == "ana@empresa.com"
    code = sent[0][1]
    assert code not in str(with_login.store.resets)  # banco guarda só o hash

    reset = lambda cd: c.post("/auth/password/reset", json={"email": "ana@empresa.com", "code": cd, "new_password": "senha-nova"})
    assert reset("ERRADO12").status_code == 400
    assert reset(code.lower()).status_code == 204          # aceita minúsculas
    assert reset(code).status_code == 400                   # uso único
    assert c.get("/auth/me", headers=ana).status_code == 401  # todas as sessões encerradas
    assert c.post("/auth/login", json={"email": "ana@empresa.com", "password": "senha-nova"}).status_code == 200


def test_codigo_de_recuperacao_esgota_tentativas(with_login):
    signup(with_login)
    auth = with_login.container.auth
    _, code = auth.request_reset("ana@empresa.com")
    for _ in range(5):
        with pytest.raises(Exception):
            auth.reset_password("ana@empresa.com", "ERRADO12", "senha-nova")
    with pytest.raises(Exception):
        auth.reset_password("ana@empresa.com", code, "senha-nova")  # certo, mas tarde demais


def test_sem_smtp_recuperacao_avisa(with_login, monkeypatch):
    monkeypatch.setattr("presentation.container.get_settings", lambda: SimpleNamespace(email_enabled=False))
    assert with_login.client.post("/auth/password/forgot", json={"email": "a@b.com"}).status_code == 503


def test_admin_limpa_sessoes_com_seguranca(with_login):
    from datetime import datetime, timedelta
    c = with_login.client
    admin, admin_user = signup(with_login)
    bia, bia_user = signup(with_login, email="bia@empresa.com", name="Bia")
    caio, _ = signup(with_login, email="caio@empresa.com", name="Caio")
    assert admin_user["role"] == "admin" and bia_user["role"] == "user"
    n_users = len(with_login.store.users)

    # usuário comum não administra; confirmação é obrigatória
    assert c.get("/admin/users", headers=bia).status_code == 403
    assert c.post("/admin/sessions/purge", headers=bia, json={"scope": "all_but_mine", "confirm": "LIMPAR"}).status_code == 403
    assert c.post("/admin/sessions/purge", headers=admin, json={"scope": "all_but_mine", "confirm": "sim"}).status_code == 422
    assert c.post("/admin/sessions/purge", headers=admin, json={"scope": "user", "user_id": "x", "confirm": "LIMPAR"}).status_code == 400
    assert len(c.get("/admin/users", headers=admin).json()) == 3

    # vencidas: só elas
    old = with_login.container.auth.open_session(with_login.store.user_by_id(bia_user["id"]))
    with_login.store.session(__import__("use_cases.auth", fromlist=["x"]).session_id(old))["expires_at"] = datetime.now() - timedelta(days=1)
    assert c.post("/admin/sessions/purge", headers=admin, json={"scope": "expired", "confirm": "LIMPAR"}).json() == {"count": 1}
    assert c.get("/auth/me", headers=bia).status_code == 200

    # de um usuário
    r = c.post("/admin/sessions/purge", headers=admin, json={"scope": "user", "user_id": bia_user["id"], "confirm": "LIMPAR"})
    assert r.json() == {"count": 1} and c.get("/auth/me", headers=bia).status_code == 401
    assert c.get("/auth/me", headers=caio).status_code == 200

    # todas menos a minha
    r = c.post("/admin/sessions/purge", headers=admin, json={"scope": "all_but_mine", "confirm": "LIMPAR"})
    assert r.json() == {"count": 1} and c.get("/auth/me", headers=caio).status_code == 401
    assert c.get("/auth/me", headers=admin).status_code == 200
    assert len(with_login.store.users) == n_users  # ninguém foi apagado


def test_banco_antigo_ganha_um_admin(with_login):
    from use_cases.auth import AuthService
    store = with_login.store
    AuthService(store).register("Ana", "ana@empresa.com", "senha-forte")
    AuthService(store).register("Bia", "bia@empresa.com", "senha-forte")
    for u in store.users.values():
        u.role = "user"  # como os usuários criados antes do papel admin
    AuthService(store).ensure_admin()
    assert [u.name for u in store.users.values() if u.is_admin] == ["Ana"]


def test_mesmo_link_dois_usuarios_um_bot_duas_reunioes(with_login):
    from domain.entities.meeting import Summary, Task
    c = with_login.client
    ana, _ = signup(with_login)
    bia, _ = signup(with_login, email="bia@empresa.com", name="Bia")
    bot = lambda h, url: c.post("/meetings/bot", headers=h, json={"meeting_url": url, "title": "Daily"})

    a = bot(ana, "https://meet.google.com/abc-defg-hij")
    assert a.status_code == 200
    # mesmo usuário, mesmo link (escrito diferente) com a reunião em andamento: 409
    dup = bot(ana, "https://MEET.google.com/abc-defg-hij/?authuser=0")
    assert dup.status_code == 409 and a.json()["meeting_id"] in dup.json()["detail"]
    b = bot(bia, "https://meet.google.com/abc-defg-hij?authuser=1")
    assert b.status_code == 200 and len(with_login.container.bots) == 1   # um bot só
    a_id, b_id = a.json()["meeting_id"], b.json()["meeting_id"]
    assert a_id != b_id

    # a gravação da Ana anda; a reunião da Bia acompanha
    src = with_login.repo.find_by_id(a_id)
    src.status = MeetingStatus.RECORDING
    with_login.repo.save(src)
    assert c.get(f"/meetings/{b_id}/status", headers=bia).json()["status"] == "recording"
    assert [m["meeting_id"] for m in c.get("/meetings/", headers=bia).json()] == [b_id]

    # terminou: a Bia recebe uma cópia própria
    src.status, src.transcript_text = MeetingStatus.DONE, "Ana: oi"
    src.summary = Summary(overview="geral", tasks=[Task("Revisar")])
    with_login.repo.save(src)
    assert c.get(f"/meetings/{b_id}", headers=bia).json()["transcript"] == "Ana: oi"
    c.patch(f"/meetings/{b_id}/tasks/0", headers=bia, json={"done": True})
    assert with_login.repo.find_by_id(a_id).summary.tasks[0].done is False   # tarefas independentes
    assert with_login.repo.find_by_id(b_id).owner_id != with_login.repo.find_by_id(a_id).owner_id

    # depois de terminar, o mesmo link volta a ser aceito
    assert bot(ana, "https://meet.google.com/abc-defg-hij").status_code == 200


def test_apagar_reuniao_preserva_gravacao_compartilhada(with_login):
    c = with_login.client
    ana, _ = signup(with_login)
    bia, _ = signup(with_login, email="bia@empresa.com", name="Bia")
    a_id = c.post("/meetings/bot", headers=ana, json={"meeting_url": "https://meet.google.com/abc-defg-hij"}).json()["meeting_id"]
    b_id = c.post("/meetings/bot", headers=bia, json={"meeting_url": "https://meet.google.com/abc-defg-hij"}).json()["meeting_id"]
    assert c.delete(f"/meetings/{a_id}", headers=ana).status_code == 409   # em andamento

    audio = with_login.tmp / "audio" / f"{a_id}.webm"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"x")
    src = with_login.repo.find_by_id(a_id)
    src.status, src.audio_path, src.transcript_text = MeetingStatus.DONE, str(audio), "Ana: oi"
    with_login.repo.save(src)

    assert c.delete(f"/meetings/{a_id}", headers=ana).status_code == 204
    assert audio.exists()                                   # a Bia ainda usa a gravação
    d = c.get(f"/meetings/{b_id}", headers=bia).json()
    assert d["status"] == "done" and d["transcript"] == "Ana: oi" and d["has_audio"]
    assert c.delete(f"/meetings/{b_id}", headers=bia).status_code == 204
    assert not audio.exists()                               # último a usar apaga


def test_smtp_recusado_mostra_o_motivo(monkeypatch):
    """O Gmail fecha a conexão depois de recusar a senha; o erro mostrado precisa ser a senha."""
    import smtplib
    import infrastructure.email.email_sender as mod

    class RejectingSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, context=None): pass
        def auth_plain(self): return ""
        def auth(self, mechanism, authobject):
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")

    cfg = SimpleNamespace(smtp_user="bot@gmail.com", smtp_password="x", smtp_from_email="", smtp_host="h",
                          smtp_port=587, email_enabled=True)
    monkeypatch.setattr(mod, "get_settings", lambda: cfg)
    monkeypatch.setattr(mod.smtplib, "SMTP", RejectingSMTP)
    with pytest.raises(RuntimeError, match="senha de app"):
        mod.EmailSender().send_password_reset("ana@empresa.com", "Ana", "ABCD2345", 15)


# ── Credenciamento do bot ────────────────────────────────────────────

class MemoryBotStore:
    def __init__(self, status="unknown"):
        self.doc = {"status": status, "message": ""}

    def get(self):
        return dict(self.doc)

    def set(self, status, message=""):
        from datetime import datetime
        self.doc = {"status": status, "message": message, "updated_at": datetime.utcnow()}


@pytest.fixture
def bot_setup(with_login, monkeypatch):
    import worker.tasks as tasks
    with_login.container.bot_account = MemoryBotStore()
    with_login.setups = []
    monkeypatch.setattr(tasks.setup_bot_task, "delay", lambda *a, **k: with_login.setups.append(k))
    return with_login


def test_bot_sem_credencial_nao_e_enviado(bot_setup):
    c = bot_setup.client
    ana, _ = signup(bot_setup)
    assert c.get("/bot/status", headers=ana).json()["status"] == "unknown"
    r = c.post("/meetings/bot", headers=ana, json={"meeting_url": "https://meet.google.com/abc-defg-hij"})
    assert r.status_code == 409 and "credenciado" in r.json()["detail"] and bot_setup.container.bots == []


def test_admin_credencia_e_libera_o_envio(bot_setup):
    c = bot_setup.client
    ana, user = signup(bot_setup)  # primeira conta = admin
    assert user["role"] == "admin"
    r = c.post("/bot/setup", headers=ana)
    assert r.status_code == 202 and r.json()["status"] == "creating" and len(bot_setup.setups) == 1
    assert c.post("/bot/setup", headers=ana).json()["status"] == "creating"
    assert len(bot_setup.setups) == 1  # já em andamento: não enfileira de novo
    bot_setup.container.bot_account.set("ready", "Conta do bot conectada")  # o worker terminou
    r = c.post("/meetings/bot", headers=ana, json={"meeting_url": "https://meet.google.com/abc-defg-hij"})
    assert r.status_code == 200 and len(bot_setup.container.bots) == 1


def test_so_admin_credencia(bot_setup):
    signup(bot_setup)
    bia, user = signup(bot_setup, email="bia@empresa.com", name="Bia")
    assert user["role"] != "admin"
    assert bot_setup.client.post("/bot/setup", headers=bia).status_code == 403
    assert bot_setup.setups == []


def test_credenciamento_parado_vira_erro(bot_setup):
    from datetime import datetime, timedelta
    store = bot_setup.container.bot_account
    store.doc = {"status": "waiting_login", "message": "", "updated_at": datetime.utcnow() - timedelta(hours=1)}
    assert bot_setup.container.bot_status()["status"] == "error"


def test_limpar_conversa_so_do_dono_e_mantem_a_reuniao(with_login):
    c, repo = with_login.client, with_login.repo
    ana, ana_user = signup(with_login)
    bia, _ = signup(with_login, email="bia@empresa.com", name="Bia")
    repo.save(Meeting(id="m1", title="Daily", owner_id=ana_user["id"], status=MeetingStatus.DONE,
                      transcript_text="Ana: oi"))
    repo.append_chat("m1", [{"role": "user", "content": "oi"}])
    docs = with_login.container.documents_dir / "m1"
    docs.mkdir(parents=True)
    (docs / "a.pdf").write_bytes(b"%PDF")
    assert c.delete("/meetings/m1/chat", headers=bia).status_code == 404  # reunião de outra pessoa
    assert repo.find_by_id("m1").chat_history
    assert c.delete("/meetings/m1/chat", headers=ana).status_code == 204
    m = repo.find_by_id("m1")
    assert m.chat_history == [] and m.transcript_text == "Ana: oi" and not docs.exists()


def test_apagar_reuniao_pela_api(with_login):
    c, repo = with_login.client, with_login.repo
    ana, ana_user = signup(with_login)
    repo.save(Meeting(id="m2", title="x", owner_id=ana_user["id"], status=MeetingStatus.RECORDING))
    assert c.delete("/meetings/m2", headers=ana).status_code == 409  # em andamento
    m = repo.find_by_id("m2"); m.status = MeetingStatus.DONE; repo.save(m)
    assert c.delete("/meetings/m2", headers=ana).status_code == 204
    assert repo.find_by_id("m2") is None and c.get("/meetings/m2", headers=ana).status_code == 404


def test_memoria_cada_um_ve_e_apaga_so_as_proprias_notas(with_login):
    from datetime import datetime
    c, mem = with_login.client, with_login.container.memory
    ana, ana_user = signup(with_login)
    bia, bia_user = signup(with_login, email="bia@empresa.com", name="Bia")
    mem.add({"_id": "n1", "owner_id": ana_user["id"], "text": "Prefiro atas curtas", "meeting_id": "",
             "created_at": datetime(2026, 11, 15)})
    assert [n["text"] for n in c.get("/memory/", headers=ana).json()] == ["Prefiro atas curtas"]
    assert c.get("/memory/", headers=bia).json() == []
    assert c.delete("/memory/n1", headers=bia).status_code == 404
    assert c.delete("/memory/n1", headers=ana).status_code == 204 and mem.list(ana_user["id"]) == []
    assert c.get("/memory/", headers=AUTH).status_code == 401  # chave de serviço não tem "minhas notas"


def test_troca_de_modo_so_admin_e_recusa_collab_sem_servicos(with_login):
    from config.settings import get_settings
    c = with_login.client
    admin, _ = signup(with_login)
    bia, _ = signup(with_login, email="bia@empresa.com", name="Bia")
    atual = get_settings().app_mode.value

    assert c.post("/admin/mode", headers=bia, json={"mode": "collab"}).status_code == 403
    assert c.post("/admin/mode", headers=admin, json={"mode": "outro"}).status_code == 422
    assert c.post("/admin/mode", headers=admin, json={"mode": atual}).json()["mode"] == atual
    if atual == "solo":
        # conftest aponta Mongo e Redis para porta morta: a troca é recusada e o modo não muda
        r = c.post("/admin/mode", headers=admin, json={"mode": "collab"})
        assert r.status_code == 409, r.text
        assert get_settings().app_mode.value == "solo"



def test_chat_em_streaming_manda_pedacos_e_a_resposta_final(ctx):
    import json as _json
    from use_cases.chat_with_meeting import ChatWithMeetingOutput
    ctx.repo.save(Meeting(id="m1", title="t", transcript_text="[00:01] Ana: oi"))

    def execute(data):
        for piece in ("Ana ", "disse ", "oi."):
            data.on_delta(piece)
        return ChatWithMeetingOutput(answer="Ana disse oi (corrigida).", success=True)
    ctx.container.chat_with_meeting = SimpleNamespace(execute=execute)
    r = ctx.client.post("/meetings/m1/chat/stream", json={"question": "o que a Ana disse?"}, headers=AUTH)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    events = [_json.loads(line) for line in r.text.splitlines()]
    assert [e["delta"] for e in events if "delta" in e] == ["Ana ", "disse ", "oi."]
    assert events[-1]["done"]["answer"] == "Ana disse oi (corrigida)."  # vale a final, não a soma dos pedaços


def test_bot_fora_do_ar_avisa_e_nao_enfileira(bot_setup):
    """2026-11-22: com a conta pronta mas nenhum worker do bot, o envio ia para a fila e nada acontecia."""
    c = bot_setup.client
    ana, _ = signup(bot_setup)
    bot_setup.container.bot_account.set("ready", "Conta do bot conectada")
    bot_setup.container._bot_worker_alive = lambda: False
    status = c.get("/bot/status", headers=ana).json()
    assert status["status"] == "offline" and "--profile bot" in status["message"]
    r = c.post("/meetings/bot", headers=ana, json={"meeting_url": "https://meet.google.com/abc-defg-hij"})
    assert r.status_code == 409 and "Nenhum bot está rodando" in r.json()["detail"]
    assert bot_setup.container.bots == []
