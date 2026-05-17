import uuid
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, HTTPException

from api.meeting import UploadResponse, MeetingStatusResponse, ProcessingStatus
from config.settings import get_settings
from presetation.container import get_container

router = APIRouter()
settings = get_settings()

# Estado em memória para status — usado apenas em modo solo
_status_store: dict[str, ProcessingStatus] = {}


def _set_status(meeting_id: str, status: ProcessingStatus) -> None:
    """Persiste status no Redis (collab) ou em memória (solo)."""
    if settings.is_collab:
        import redis as redis_client
        r = redis_client.from_url(settings.redis_url)
        r.set(f"status:{meeting_id}", status.value, ex=86400)
    else:
        _status_store[meeting_id] = status


def _get_status(meeting_id: str) -> ProcessingStatus | None:
    """Lê status do Redis (collab) ou da memória (solo)."""
    if settings.is_collab:
        import redis as redis_client
        r = redis_client.from_url(settings.redis_url)
        val = r.get(f"status:{meeting_id}")
        return ProcessingStatus(val.decode()) if val else None
    return _status_store.get(meeting_id)


@router.post("/upload", response_model=UploadResponse)
async def upload_meeting(
    file: UploadFile = File(...),
    title: str = "Reunião sem título",
):
    """Recebe áudio, salva e enfileira processamento."""
    meeting_id = str(uuid.uuid4())

    audio_dir = Path(settings.audio_storage_path)
    audio_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "audio.wav").suffix
    audio_path = str(audio_dir / f"{meeting_id}{suffix}")

    with open(audio_path, "wb") as f:
        f.write(await file.read())

    _set_status(meeting_id, ProcessingStatus.PENDING)

    # Modo collab → enfileira no Celery
    # Modo solo → processa direto (bloqueante, mas simples)
    if settings.is_collab:
        from worker.tasks import process_meeting_task
        process_meeting_task.delay(meeting_id, audio_path, title)
    else:
        _process_sync(meeting_id, audio_path, title)

    return UploadResponse(
        meeting_id=meeting_id,
        status=_get_status(meeting_id),
        message="Áudio recebido. Processamento iniciado.",
    )


@router.get("/{meeting_id}/status", response_model=MeetingStatusResponse)
def get_status(meeting_id: str):
    """Retorna status e dados da reunião."""
    container = get_container()
    meeting = container.repository.find_by_id(meeting_id)

    if not meeting:
        status = _get_status(meeting_id)
        if not status:
            raise HTTPException(404, "Reunião não encontrada")
        return MeetingStatusResponse(
            meeting_id=meeting_id,
            status=status,
            title="Processando...",
            started_at=datetime.now(),
        )

    return MeetingStatusResponse(
        meeting_id=meeting_id,
        status=ProcessingStatus.DONE,
        title=meeting.title,
        started_at=meeting.started_at,
        duration_minutes=meeting.duration_minutes,
        participants=meeting.participants,
        summary=_map_summary(meeting.summary) if meeting.summary else None,
    )


@router.get("/", response_model=list[MeetingStatusResponse])
def list_meetings():
    container = get_container()
    meetings = container.repository.list_all()
    return [
        MeetingStatusResponse(
            meeting_id=m.id,
            status=ProcessingStatus.DONE,
            title=m.title,
            started_at=m.started_at,
            duration_minutes=m.duration_minutes,
            participants=m.participants,
        )
        for m in meetings
    ]


def _process_sync(meeting_id: str, audio_path: str, title: str) -> None:
    """Processamento síncrono — modo solo."""
    from entities.metting import Meeting
    from user_cases.transcribe_meeting import TranscribeMeetingInput
    from user_cases.summarize_metting import SummarizeMeetingInput

    container = get_container()
    _set_status(meeting_id, ProcessingStatus.TRANSCRIBING)

    t_result = container.transcribe_meeting.execute(
        TranscribeMeetingInput(audio_path=audio_path, with_diarization=True)
    )
    if not t_result.success:
        _set_status(meeting_id, ProcessingStatus.ERROR)
        return

    meeting = Meeting(
        id=meeting_id, title=title,
        started_at=datetime.now(),
        audio_path=audio_path,
        transcript_text=t_result.transcript.full_text,
        transcript_formatted=t_result.transcript.formatted,
        participants=t_result.transcript.speakers,
        duration_minutes=t_result.transcript.duration_minutes,
    )

    _set_status(meeting_id, ProcessingStatus.SUMMARIZING)
    s_result = container.summarize_meeting.execute(
        SummarizeMeetingInput(meeting=meeting)
    )
    _set_status(
        meeting_id,
        ProcessingStatus.DONE if s_result.success else ProcessingStatus.ERROR,
    )


def _map_summary(summary):
    from api.meeting import SummarySchema, TaskSchema, DecisionSchema
    return SummarySchema(
        overview=summary.overview,
        topics=summary.topics,
        tasks=[TaskSchema(description=t.description, responsible=t.responsible,
                         deadline=t.deadline, done=t.done) for t in summary.tasks],
        decisions=[DecisionSchema(description=d.description, context=d.context)
                   for d in summary.decisions],
    )