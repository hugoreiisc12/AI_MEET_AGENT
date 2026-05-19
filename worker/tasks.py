"""
worker/tasks.py — Tasks Celery para processamento assíncrono.

Ativado apenas em modo colaborativo (APP_MODE=collab).
Cada áudio enviado vira uma task independente processada por um worker.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import uuid
from datetime import datetime

from config.settings import get_settings

settings = get_settings()

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
except ImportError:
    celery_app = None  # modo solo — Celery não instalado


def process_meeting_task_fn(meeting_id: str, audio_path: str, title: str) -> dict:
    """
    Lógica real de processamento — separada do decorator Celery
    para ser testável sem broker.
    """
    from entities.meeting import Meeting
    from use_cases.transcribe_meeting import TranscribeMeetingInput
    from use_cases.summarize_meeting import SummarizeMeetingInput
    from presentation.container import get_container

    container = get_container()

    # 1. Transcrição
    t_result = container.transcribe_meeting.execute(
        TranscribeMeetingInput(audio_path=audio_path, with_diarization=True)
    )
    if not t_result.success:
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
    s_result = container.summarize_meeting.execute(
        SummarizeMeetingInput(meeting=meeting)
    )
    if not s_result.success:
        return {"status": "error", "error": s_result.error_message}

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
    def process_meeting_task(*args, **kwargs):
        raise RuntimeError("Celery não instalado. Use APP_MODE=solo.")