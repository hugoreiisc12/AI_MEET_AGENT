"""
container.py — único ponto de composição (injeção de dependência).

Os modos diferem só em dois pontos (ADR-004):
  collab (produção)      → MongoDB + fila Celery
  solo (desenvolvimento) → JSON local + thread
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Optional

from config.settings import get_settings
from domain.entities.meeting import Meeting, MeetingStatus
from domain.entities.user import User
from infrastructure.llm.meeting_agent import MeetingAgent
from use_cases.chat_with_meeting import ChatWithMeetingUC
from use_cases.process_meeting import ProcessMeetingInput, ProcessMeetingUC
from use_cases.summarize_meeting import SummarizeMeetingUC
from use_cases.transcribe_meeting import TranscribeMeetingUC

logger = logging.getLogger(__name__)

STALL_S = 90  # etapa sem worker nem fila por mais que isso = travada
BOT_SETUP_STALE_MIN = 15  # mais que WAIT_HUMAN_S do bot_setup (10 min)
_ACTIVE = (MeetingStatus.PENDING, MeetingStatus.RECORDING, MeetingStatus.TRANSCRIBING, MeetingStatus.SUMMARIZING)
_FINAL = (MeetingStatus.DONE, MeetingStatus.ERROR)
# O que a reunião de quem chegou depois copia da gravação de quem mandou o bot primeiro.
_SHARED = ("status", "status_at", "error", "started_at", "audio_path", "transcript_text", "transcript_formatted",
           "transcript_raw", "summary", "participants", "duration_minutes", "metrics")


_LOCAL_LOCK = threading.Lock()


class BotNotReady(Exception):
    """O bot ainda não tem conta do Google conectada: credenciar antes de mandar a reuniões."""


class MeetingInProgress(Exception):
    """O usuário já mandou o bot a este link e a reunião ainda não acabou."""

    def __init__(self, meeting_id: str) -> None:
        super().__init__("O bot já está a caminho desta reunião ou gravando. Acompanhe a reunião já criada.")
        self.meeting_id = meeting_id


def _build_transcriber(settings):
    if settings.use_local_whisper:
        from infrastructure.transcriber.whisper_local_transcriber import WhisperLocalTranscriber
        return WhisperLocalTranscriber()

    if settings.use_real_diarization:
        from infrastructure.transcriber.whisper_with_diarization import WhisperWithDiarization
        return WhisperWithDiarization()

    from infrastructure.transcriber.whisper_transcriber import WhisperTranscriber
    return WhisperTranscriber()


def _build_repository(settings):
    if settings.is_collab:
        from infrastructure.mongo_meeting_repository import MongoMeetingRepository
        return MongoMeetingRepository(settings.mongo_uri, settings.mongo_db)

    from infrastructure.json_meeting_repository import JsonMeetingRepository
    return JsonMeetingRepository(settings.storage_path)


def _chat_metrics(path: str, seconds: float) -> None:
    """Caminho de cada resposta do chat (S14-4): cache, quente (trechos na memória) ou banco."""
    from infrastructure import observability as obs
    obs.incr("chat_answers_total", {"path": path})
    obs.observe("chat_seconds", seconds, {"path": path})


BOT_OFFLINE_MESSAGE = ("Nenhum bot está rodando para entrar nas reuniões. Suba o bot com "
                       "`docker compose --profile bot up -d bot` (ou, no Mac, `python main.py --bot-worker`).")


class Container:
    indexer = None  # memória do agente; montada no __init__

    def __init__(self) -> None:
        settings = get_settings()
        llm = MeetingAgent()

        self._is_collab = settings.is_collab
        # Opcional (ENABLE_CALENDAR): dá título à reunião a partir da agenda.
        self.calendar = None
        if settings.enable_calendar:
            from infrastructure.calendar.google_calendar_service import GoogleCalendarService
            self.calendar = GoogleCalendarService(settings.google_credentials_path, settings.google_token_path)
        # CAG (ADR-022, S14-3): respostas em cache por dono; toda gravação de reunião ou nota invalida.
        from infrastructure.hot_cache import build_hot_cache
        from use_cases.agent_cache import AgentCache, InvalidatingMemory, InvalidatingRepository
        # MEMORY_V2=false: agente da v1.0 (sem cache, sem índice; o contrato v1 vem do MeetingAgent).
        self.agent_cache = AgentCache(build_hot_cache(settings)) if settings.memory_v2 else None
        self.repository = _build_repository(settings)
        if self.agent_cache:
            self.repository = InvalidatingRepository(self.repository, self.agent_cache)
        # Login de usuários (ADR-011) nos dois modos: MongoDB no collab, arquivo JSON no solo.
        # As contas não se misturam: quem troca de modo entra com uma conta do outro armazenamento.
        from infrastructure.auth_store import JsonAuthStore, MongoAuthStore
        from use_cases.auth import AuthService
        store = (MongoAuthStore(settings.mongo_uri, settings.mongo_db) if settings.is_collab
                 else JsonAuthStore(str(Path(settings.storage_path).parent / "auth.json")))
        self.auth = AuthService(store, session_days=settings.session_days,
                                allow_registration=settings.allow_registration)
        try:
            self.auth.ensure_admin()
        except Exception as exc:  # banco fora na partida: tenta de novo na próxima
            logger.warning("Não foi possível conferir o admin: %s", exc)
        # Credenciamento da conta do bot pela interface: só em collab (bot na fila).
        self.bot_account = None
        if settings.is_collab:
            from infrastructure.bot_account_store import BotAccountStore
            self.bot_account = BotAccountStore(settings.mongo_uri, settings.mongo_db)
        self.transcribe_meeting = TranscribeMeetingUC(_build_transcriber(settings))
        # Quanto cabe por pedido, pela janela do modelo (ModelProfile): no piso (32k) dá os 30 mil de sempre.
        from infrastructure.llm.model_client import CHARS_PER_TOKEN, NUM_PREDICT
        window_chars = int((llm._budget.window_tokens - NUM_PREDICT) * CHARS_PER_TOKEN)
        meeting_chars = min(settings.llm_context_chars, int(window_chars * 0.45))
        self.summarize_meeting = SummarizeMeetingUC(llm, max_context_chars=meeting_chars)
        from infrastructure.exporters.document_writer import write_document
        self.documents_dir = Path(settings.documents_path)
        if settings.is_collab:
            from infrastructure.memory_store import MongoMemoryStore
            self.memory = MongoMemoryStore(settings.mongo_uri, settings.mongo_db)
        else:
            from infrastructure.memory_store import JsonMemoryStore
            self.memory = JsonMemoryStore(str(Path(settings.storage_path).parent / "memories.json"))
        if self.agent_cache:
            self.memory = InvalidatingMemory(self.memory, self.agent_cache)
        # Memória longa do agente (ADR-022): trechos com vetor e entidades em data/index, que a API e
        # os workers compartilham. O modelo de embeddings só carrega no primeiro uso.
        from infrastructure.embeddings import build_embedder
        from infrastructure.index_store import IndexStore
        from use_cases.meeting_index import MemoryIndexer
        # Montado sempre (o modelo só carrega no primeiro uso): mesmo com MEMORY_V2=false, apagar uma
        # reunião limpa o índice dela. Chat e pipeline só o usam com a flag ligada.
        self.indexer = MemoryIndexer(IndexStore(str(Path(settings.storage_path).parent / "index")),
                                     build_embedder(settings))
        memory_v2_indexer = self.indexer if settings.memory_v2 else None
        self.chat_with_meeting = ChatWithMeetingUC(
            llm, repository=self.repository, max_context_chars=meeting_chars, window_chars=window_chars,
            documents_dir=self.documents_dir, write_document=_counted_write_document(write_document),
            memory_store=self.memory, indexer=memory_v2_indexer, agent_cache=self.agent_cache,
            metrics=_chat_metrics,
        )
        from infrastructure.recorder.speaker_events import load_speaker_events
        self.process_meeting = ProcessMeetingUC(
            self.transcribe_meeting, self.summarize_meeting, self.repository,
            load_speaker_events=lambda audio: load_speaker_events(audio, exclude=(settings.bot_name, "Você", "You")),
            indexer=memory_v2_indexer,
        )

    def register_user(self, name: str, email: str, password: str) -> User:
        """Cadastra. O primeiro usuário herda as reuniões gravadas antes de existir login."""
        user = self.auth.register(name, email, password)
        if self.auth.is_first_user():
            for meeting in self.repository.list_all(owner_id=""):
                meeting.owner_id = user.id
                self.repository.save(meeting)
        return user

    def send_password_reset(self, email: str) -> None:
        """Envia o código de nova senha. Não diz se o e-mail tem conta.
        RuntimeError se o SMTP não estiver configurado."""
        from infrastructure.email.email_sender import EmailSender
        from use_cases.auth import RESET_MINUTES
        if not get_settings().email_enabled:
            raise RuntimeError("Recuperação de senha indisponível: o e-mail (SMTP) não está configurado.")
        result = self.auth.request_reset(email)
        if result:
            user, code = result
            EmailSender().send_password_reset(user.email, user.name, code, RESET_MINUTES)

    def meeting_for(self, meeting_id: str, owner_id: Optional[str]) -> Optional[Meeting]:
        """A reunião, se existir e for de `owner_id` (None = sem restrição de dono)."""
        meeting = self.repository.find_by_id(meeting_id)
        if meeting is None or (owner_id is not None and meeting.owner_id != owner_id):
            return None
        return self._follow(meeting)

    def meetings_of(self, owner_id: Optional[str]) -> list[Meeting]:
        return [self._follow(m) for m in self.repository.list_all(owner_id)]

    def _follow(self, meeting: Meeting) -> Meeting:
        """Reunião que espera a gravação de outro usuário: acompanha o status dela e,
        quando ela termina, recebe uma cópia própria do resultado (chat e tarefas à parte)."""
        if not meeting.source_id:
            return meeting
        source = self.repository.find_by_id(meeting.source_id)
        if source is None:
            meeting.status = MeetingStatus.ERROR
            meeting.error = "A gravação foi apagada antes de ficar pronta."
            meeting.source_id = ""
        else:
            before = [getattr(meeting, f) for f in _SHARED]
            for f in _SHARED:
                setattr(meeting, f, getattr(source, f))
            if source.status in _FINAL:
                meeting.source_id = ""  # a partir daqui a reunião é independente
            elif [getattr(meeting, f) for f in _SHARED] == before:
                return meeting
        self.repository.save(meeting)
        return meeting

    def delete_meeting(self, meeting: Meeting) -> None:
        """Apaga a reunião. A gravação fica se outra reunião ainda usa o mesmo áudio."""
        if meeting.status in _ACTIVE:
            raise MeetingInProgress(meeting.id)
        for follower in self.repository.find_by(source_id=meeting.id):
            self._follow(follower)  # copia o resultado antes de a fonte sumir
        self.repository.delete(meeting.id)
        if self.indexer:
            self.indexer.forget(meeting)  # trechos e menções saem junto: nada da reunião apagada fica no índice
        shutil.rmtree(self.documents_dir / meeting.id, ignore_errors=True)  # documentos gerados no chat
        if meeting.audio_path and not self.repository.find_by(audio_path=meeting.audio_path):
            audio = Path(meeting.audio_path)  # com a gravação, os arquivos auxiliares (.speakers.jsonl…)
            for f in audio.parent.glob(f"{audio.name.split('.')[0]}.*"):
                f.unlink(missing_ok=True)

    def enqueue_processing(
        self, meeting_id: str, audio_path: str, title: str, wait: bool = False, owner_id: str = "",
    ) -> None:
        """Registra a reunião como pendente e despacha o processamento.

        wait=True é para processos que encerram logo em seguida (CLI, run_bot):
        em solo roda na própria chamada, porque uma thread não sobrevive ao fim
        do interpretador. Em collab é ignorado — a fila é quem executa.
        """
        meeting = self.repository.find_by_id(meeting_id) or Meeting(id=meeting_id, title=title, owner_id=owner_id)
        meeting.audio_path = audio_path
        meeting.status, meeting.error = MeetingStatus.PENDING, ""

        if self._is_collab:
            self.enqueue(meeting, "transcribe", title=title)
            return

        self.repository.save(meeting)
        data = ProcessMeetingInput(meeting_id, audio_path, title)
        if wait:
            self.process_meeting.execute(data)
        else:
            threading.Thread(
                target=self.process_meeting.execute, args=(data,),
                name=f"process-{meeting_id[:8]}", daemon=True,
            ).start()

    def enqueue(self, meeting: Meeting, queue: str, title: str = "") -> None:
        """Põe a reunião na fila de uma etapa ("transcribe" ou "llm") do Celery (ADR-015)."""
        from worker.tasks import process_meeting_task, summarize_meeting_task
        meeting.queue = queue
        meeting.queue_priority = self._priority(meeting)
        meeting.queued_at = datetime.now()
        self.repository.save(meeting)
        if queue == "transcribe":
            process_meeting_task.apply_async((meeting.id, meeting.audio_path, title or meeting.title),
                                             priority=meeting.queue_priority)
        else:
            summarize_meeting_task.apply_async((meeting.id,), priority=meeting.queue_priority)

    def _priority(self, meeting: Meeting) -> int:
        """Quantas reuniões do mesmo dono já estão na fila ou em processamento (0 a 9).

        Justiça entre usuários (S9-3): o 1º envio de cada usuário tem prioridade 0; o 10º
        de quem mandou dez vai depois do 1º de quem mandou um. Ninguém é recusado.
        """
        busy = [m for m in self.repository.list_all(meeting.owner_id)
                if m.id != meeting.id and not m.source_id
                and (m.queue or m.status in (MeetingStatus.TRANSCRIBING, MeetingStatus.SUMMARIZING))]
        return min(len(busy), 9)

    def queue_position(self, meeting: Meeting) -> int:
        """Posição na fila da etapa (1 = é a próxima); 0 se não está esperando.
        Conta reuniões de todos os usuários, na ordem em que o Celery as entrega."""
        target = self.repository.find_by_id(meeting.source_id) if meeting.source_id else meeting
        if target is None or not target.queue or target.queued_at is None:
            return 0
        mine = (target.queue_priority, target.queued_at)
        ahead = [m for m in self.repository.find_by(queue=target.queue)
                 if m.id != target.id and m.queued_at and (m.queue_priority, m.queued_at) < mine]
        return len(ahead) + 1

    def progress(self, meeting: Meeting) -> dict:
        """Há quanto tempo a etapa atual roda, quanto ela costuma levar e se travou.

        Travou = gravando, transcrevendo ou resumindo, sem worker nenhum com essa reunião
        (batimento, ADR-019), fora da fila e há mais de STALL_S. Acontece quando um worker morre
        no meio; antes a tela ficava em "Transcrevendo…" para sempre, sem aviso."""
        from infrastructure import observability as obs
        source = self.repository.find_by_id(meeting.source_id) if meeting.source_id else meeting
        source = source or meeting
        elapsed = (datetime.now() - source.status_at).total_seconds() if source.status_at else None
        state = "working"
        if source.status in (MeetingStatus.RECORDING, MeetingStatus.TRANSCRIBING, MeetingStatus.SUMMARIZING):
            if source.queue:
                state = "queued"
            elif elapsed is not None and elapsed > STALL_S:
                alive = obs.workers()
                if alive is not None and not any(
                        (w.get("task") or {}).get("meeting_id") == source.id for ws in alive.values() for w in ws):
                    state = "stalled"
        stage = {MeetingStatus.TRANSCRIBING: "transcribe", MeetingStatus.SUMMARIZING: "summarize"}.get(source.status)
        typical = None
        if stage:
            values = obs.samples().get(f"pipeline_stage_seconds|stage={stage}", [])
            typical = obs.percentile(values, 50) if len(values) >= 3 else None
        return {"state": state, "elapsed_s": elapsed, "typical_s": typical}

    def resume(self, meeting: Meeting) -> None:
        """Retoma uma reunião travada (ver progress) a partir da etapa em que parou."""
        if meeting.status in (MeetingStatus.RECORDING, MeetingStatus.TRANSCRIBING):
            audio = Path(meeting.audio_path or "")
            if meeting.audio_path and audio.exists() and audio.stat().st_size > 0:
                self.enqueue_processing(meeting.id, meeting.audio_path, meeting.title)
            else:
                meeting.status, meeting.error = MeetingStatus.ERROR, "O bot parou de responder e não há áudio gravado."
                self.repository.save(meeting)
        elif meeting.status is MeetingStatus.SUMMARIZING:
            if self._is_collab:
                self.enqueue(meeting, "llm")
            else:
                threading.Thread(target=self.process_meeting.summarize, args=(meeting.id,), daemon=True).start()
        else:
            raise ValueError("A reunião não está parada numa etapa.")

    def clear_chat(self, meeting: Meeting) -> None:
        """Apaga a conversa da reunião, com os documentos gerados nela e os e-mails não enviados.
        A reunião (resumo, transcrição, tarefas) fica."""
        meeting.chat_history = []
        self.repository.set_chat_history(meeting.id, [])
        shutil.rmtree(self.documents_dir / meeting.id, ignore_errors=True)

    def chat_action(self, meeting: Meeting, action_id: str) -> dict:
        for msg in meeting.chat_history:
            action = msg.get("action")
            if action and action.get("id") == action_id:
                return action
        raise LookupError("Ação não encontrada")

    def resolve_email_action(self, meeting: Meeting, action_id: str, send: bool) -> dict:
        """Envia (send=True) ou descarta o e-mail que o agente preparou no chat.
        RuntimeError se o SMTP falhar: o e-mail continua pendente para tentar de novo."""
        action = self.chat_action(meeting, action_id)
        if action["type"] != "email":
            raise LookupError("Ação não encontrada")
        if action["status"] != "pending":
            raise ValueError(f"Este e-mail já foi {'enviado' if action['status'] == 'sent' else 'descartado'}.")
        if send:
            if not get_settings().email_enabled:
                raise RuntimeError("Envio de e-mail indisponível: o SMTP não está configurado.")
            from infrastructure.email.email_sender import EmailSender
            from use_cases.chat_with_meeting import document_path
            files = []
            for att in action.get("attachments") or []:
                path = document_path(self.documents_dir, meeting.id, att["id"], att["format"])
                if not path.exists():  # nunca mandar o e-mail sem o anexo prometido
                    raise RuntimeError(f"O anexo {att['filename']} não está mais disponível. "
                                       "Descarte este e-mail e peça o documento de novo.")
                files.append((att["filename"], path.read_bytes()))
            EmailSender().send_message(action["to"], action["subject"], action["body"], files)
            action["status"], action["sent_at"] = "sent", datetime.now().isoformat(timespec="seconds")
            logger.info("[%s] e-mail do chat enviado para %d destinatário(s)", meeting.id, len(action["to"]))
        else:
            action["status"] = "canceled"
        self.repository.set_chat_history(meeting.id, meeting.chat_history)
        return action

    def document_file(self, meeting: Meeting, action_id: str) -> tuple[Path, dict]:
        from use_cases.chat_with_meeting import document_path
        action = self.chat_action(meeting, action_id)
        path = document_path(self.documents_dir, meeting.id, action_id, action.get("format", ""))
        if action["type"] != "document" or not path.exists():
            raise LookupError("Documento não encontrado")
        return path, action

    def set_task_done(self, meeting_id: str, index: int, done: bool, owner_id: Optional[str] = None) -> Meeting:
        """Marca ou desmarca uma tarefa da reunião e grava."""
        meeting = self.meeting_for(meeting_id, owner_id)
        if meeting is None:
            raise LookupError("Reunião não encontrada")
        tasks = meeting.summary.tasks if meeting.summary else []
        if not 0 <= index < len(tasks):
            raise LookupError("Tarefa não encontrada")
        tasks[index].done = done
        self.repository.save(meeting)
        return meeting

    def upcoming_events(self, limit: int = 8) -> tuple[list, str]:
        """(próximas reuniões da agenda com link, erro). Agenda desligada: ([], "")."""
        if self.calendar is None:
            return [], ""
        try:
            return self.calendar.get_upcoming_events(limit=limit), ""
        except Exception as exc:  # agenda é um extra: mostra o motivo, não derruba a tela
            logger.warning("Agenda indisponível: %s", exc)
            return [], str(exc)

    def _title_from_calendar(self, meeting_url: str) -> str:
        if self.calendar is None:
            return ""
        try:
            event = self.calendar.find_by_meet_url(meeting_url)
            return event.title if event else ""
        except Exception as exc:  # agenda é um extra: nunca impede o bot de entrar
            logger.warning("Agenda indisponível: %s", exc)
            return ""

    def _link_lock(self, key: str):
        """Trava por link de reunião. Em collab fica no Redis (vale entre processos e
        máquinas); em solo há um processo só e basta uma trava local."""
        if not self._is_collab:
            return _LOCAL_LOCK
        import redis
        client = redis.Redis.from_url(get_settings().redis_url, socket_timeout=5)
        # timeout: a trava some sozinha se o processo morrer segurando; blocking_timeout:
        # quem chega depois espera o primeiro terminar (milissegundos) e, sem Redis, falha.
        return client.lock(f"lock:bot-link:{key}", timeout=10, blocking_timeout=5)

    def bot_status(self) -> dict:
        """{"status", "message", "vnc_url"}. Em solo não há credenciamento: sempre pronto."""
        if self.bot_account is None:
            return {"status": "ready", "message": "", "vnc_url": ""}
        doc = self.bot_account.get()
        status, message = doc.get("status", "unknown"), doc.get("message", "")
        # Credenciamento sem notícia há muito tempo: o worker morreu no meio.
        updated = doc.get("updated_at")
        if status in ("creating", "waiting_login") and updated and \
                datetime.utcnow() - updated > timedelta(minutes=BOT_SETUP_STALE_MIN):
            status, message = "error", "O credenciamento foi interrompido. Tente de novo."
        # Conta pronta não basta: sem um worker do bot vivo, o pedido fica parado na fila e nada acontece
        # na tela (2026-11-22: "Teste 002" ficou em pending com o bot fora do ar).
        if status == "ready" and not self._bot_worker_alive():
            status, message = "offline", BOT_OFFLINE_MESSAGE
        return {"status": status, "message": message, "vnc_url": get_settings().bot_vnc_url}

    @staticmethod
    def _bot_worker_alive() -> bool:
        """Pelo batimento no Redis (ADR-015), que o worker do bot grava no container ou no Mac. Sem
        leitura do Redis, não bloqueia: o envio segue e a fila espera."""
        from infrastructure import observability as obs
        alive = obs.workers()
        return alive is None or bool(alive.get("bot"))

    def request_bot_setup(self) -> dict:
        """Põe o credenciamento na fila do bot. Se já houver um em andamento, só devolve o estado."""
        current = self.bot_status()
        if current["status"] in ("creating", "waiting_login"):
            return current
        from worker.tasks import setup_bot_task
        self.bot_account.set("creating", "Na fila do bot (espera terminar a reunião em andamento, se houver)")
        setup_bot_task.delay()
        return self.bot_status()

    def dispatch_bot(self, meeting_url: str, title: str = "", owner_id: str = "") -> str:
        """Manda o bot para a reunião sem bloquear. Retorna o id da reunião.
        Sem título, usa o do evento na agenda (se ligada) ou a data."""
        from infrastructure.recorder.platforms import detect_platform, meeting_key
        platform = detect_platform(meeting_url)  # ValueError com mensagem para o usuário
        bot = self.bot_status()
        if bot["status"] == "offline":
            raise BotNotReady(bot["message"])
        if bot["status"] != "ready":
            raise BotNotReady("O bot ainda não foi credenciado. Clique em \"Credenciar bot\" (administrador).")
        key = meeting_key(meeting_url)
        title = (title or "").strip() or self._title_from_calendar(meeting_url) \
            or f"Reunião {datetime.now():%d/%m/%Y %H:%M}"

        # Mesma reunião já com o bot a caminho ou gravando: não manda um segundo bot. A trava
        # por link cobre "conferir e gravar": dois envios no mesmo instante (inclusive em
        # processos diferentes da API) viram uma gravação e uma reunião que a acompanha.
        with self._link_lock(key):
            active = [self._follow(m) for m in self.repository.find_by(meeting_url=key)]
            active = [m for m in active if m.status in (MeetingStatus.PENDING, MeetingStatus.RECORDING)]
            mine = next((m for m in active if m.owner_id == owner_id), None)
            if mine:
                raise MeetingInProgress(mine.id)
            meeting = Meeting(id=str(uuid.uuid4()), title=title, owner_id=owner_id,
                              platform=platform.key, meeting_url=key)
            source = next((m for m in active if not m.source_id), None)
            if source:
                meeting.source_id = source.id
                self.repository.save(self._follow(meeting))
                return meeting.id
            meeting_id = meeting.id
            self.repository.save(meeting)

        if self._is_collab:
            from worker.tasks import join_meeting_task
            join_meeting_task.delay(meeting_id, meeting_url, title)
        else:
            subprocess.Popen([
                sys.executable, "-m", "infrastructure.recorder.run_bot",
                "--url", meeting_url, "--title", title, "--meeting-id", meeting_id,
            ])
        return meeting_id


def _counted_write_document(write):
    def wrapper(path, fmt, *args, **kwargs):
        from infrastructure import observability as obs
        result = write(path, fmt, *args, **kwargs)
        obs.incr("documents_total", {"format": fmt})
        return result
    return wrapper


@lru_cache(maxsize=1)
def get_container() -> Container:
    return Container()
