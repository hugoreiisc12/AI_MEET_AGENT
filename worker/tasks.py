"""
worker/tasks.py — Tasks Celery para processamento assíncrono.

Ativado apenas em modo colaborativo (APP_MODE=collab).
Cada áudio enviado vira uma task independente processada por um worker.

WINDOWS SUPPORT: Se Celery não funcionar (ex: no Windows), usa threading em memória.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import uuid
import threading
import queue
from datetime import datetime
from typing import Dict, Any

from config.settings import get_settings

settings = get_settings()

# Store de status em memória (fallback para Windows)
_task_status: Dict[str, str] = {}
_task_status_lock = threading.Lock()
_task_queue: queue.Queue = queue.Queue()
_worker_started = False  # Flag para evitar múltiplas inicializações
_worker_lock = threading.Lock()

try:
    from celery import Celery
    celery_app = Celery(
        "meet_agent",
        broker=settings.redis_url,
        backend=settings.redis_url,
    )
    celery_app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="America/Sao_Paulo",
        task_track_started=True,
    )
    HAS_CELERY = True
except ImportError:
    celery_app = None  # modo solo — Celery não instalado
    HAS_CELERY = False


def _set_status(meeting_id: str, status_value: str) -> None:
    """
    Atualiza status no Redis diretamente — sem importar o router da API.
    FIX: o worker não pode importar _set_status de api/routers/meetings.py
    pois isso cria dependência circular (worker → api → container → worker).
    
    WINDOWS SUPPORT: Se Redis não funcionar, usa memória local.
    """
    if HAS_CELERY:
        # Modo collab com Celery — usa Redis
        try:
            import redis as redis_lib
            r = redis_lib.from_url(settings.redis_url)
            r.set(f"status:{meeting_id}", status_value, ex=86400)
        except Exception:
            # Fallback: atualiza também em memória
            with _task_status_lock:
                _task_status[meeting_id] = status_value
    else:
        # Modo Windows: store em memória
        with _task_status_lock:
            _task_status[meeting_id] = status_value


def get_task_status(meeting_id: str) -> str:
    """Obtém status da task (do Redis ou da memória)."""
    if HAS_CELERY:
        try:
            import redis as redis_lib
            r = redis_lib.from_url(settings.redis_url)
            status = r.get(f"status:{meeting_id}")
            if status:
                return status.decode() if isinstance(status, bytes) else status
        except Exception:
            pass
    
    # Fallback: consulta memória
    with _task_status_lock:
        return _task_status.get(meeting_id, "unknown")


def process_meeting_task_fn(meeting_id: str, audio_path: str, title: str) -> dict:
    """
    Lógica real de processamento — separada do decorator Celery
    para ser testável sem broker.
    """
    from domain.entities.meeting import Meeting
    from use_cases.transcribe_meeting import TranscribeMeetingInput
    from use_cases.summarize_meeting import SummarizeMeetingInput
    from presentation.container import get_container

    container = get_container()

    # 1. Transcrição
    _set_status(meeting_id, "transcribing")  # FIX: era omitido
    t_result = container.transcribe_meeting.execute(
        TranscribeMeetingInput(audio_path=audio_path, with_diarization=True)
    )
    if not t_result.success:
        _set_status(meeting_id, "error")      # FIX: era omitido
        return {"status": "error", "error": t_result.error_message}

    transcript = t_result.transcript
    meeting = Meeting(
        id=meeting_id,
        title=title,
        started_at=datetime.now(),
        audio_path=audio_path,
        transcript_text=transcript.full_text,
        transcript_formatted=transcript.formatted,
        participants=transcript.speakers,
        duration_minutes=transcript.duration_minutes,
    )

    # 2. Resumo
    _set_status(meeting_id, "summarizing")   # FIX: era omitido
    s_result = container.summarize_meeting.execute(
        SummarizeMeetingInput(meeting=meeting)
    )
    if not s_result.success:
        _set_status(meeting_id, "error")      # FIX: era omitido
        return {"status": "error", "error": s_result.error_message}

    # 3. Persistir reunião no repositório               # FIX: era omitido
    meeting.summary = s_result.summary
    container.repository.save(meeting)

    _set_status(meeting_id, "done")           # FIX: era omitido
    return {"status": "done", "meeting_id": meeting_id}


if celery_app:
    @celery_app.task(
        name="process_meeting",
        bind=True,
        max_retries=3,
        default_retry_delay=30,
    )
    def process_meeting_task(self, meeting_id: str, audio_path: str, title: str):
        try:
            return process_meeting_task_fn(meeting_id, audio_path, title)
        except Exception as exc:
            raise self.retry(exc=exc)
else:
    # FALLBACK WINDOWS: sem Celery, usa threading em memória
    def process_meeting_task(meeting_id: str, audio_path: str, title: str):
        """
        Fallback para Windows/desenvolvimento local.
        Enfileira a task e processa em thread separada.
        """
        _task_queue.put((meeting_id, audio_path, title))
        return {"status": "queued", "meeting_id": meeting_id}

    process_meeting_task.delay = process_meeting_task  # compatibilidade com .delay()


def _worker_loop():
    """
    Loop do worker que processa tasks da fila em memória.
    Executa em thread separada (background).
    Apenas usado quando Celery não está disponível (Windows).
    """
    while True:
        try:
            meeting_id, audio_path, title = _task_queue.get(timeout=1)
            result = process_meeting_task_fn(meeting_id, audio_path, title)
            print(f"✅ Task {meeting_id} concluída: {result['status']}")
        except queue.Empty:
            continue
        except Exception as e:
            print(f"❌ Erro ao processar task: {e}")


def start_background_worker() -> None:
    """
    Inicia worker em background thread (apenas para Windows/desenvolvimento).
    Chamado uma única vez na inicialização.
    Protegido contra múltiplas inicializações com flag thread-safe.
    """
    global _worker_started
    
    if HAS_CELERY:
        return  # Não precisa do fallback com Celery
    
    with _worker_lock:
        if _worker_started:
            return  # Já foi iniciado
        
        _worker_started = True
        worker_thread = threading.Thread(target=_worker_loop, daemon=True)
        worker_thread.start()
        print("🔧 Worker em background (modo Windows) iniciado com sucesso")