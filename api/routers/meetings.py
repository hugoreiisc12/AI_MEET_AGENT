import uuid
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, HTTPException
import redis

from api.meeting import UploadResponse, MeetingStatusResponse, ProcessingStatus
from config.settings import get_settings
from presentation.container import get_container

router = APIRouter()
settings = get_settings()

# Estado em memória para status — usado apenas em modo solo
_status_store: dict[str, ProcessingStatus] = {}


def _set_status(meeting_id: str, status: ProcessingStatus) -> None:
    """Persiste status no Redis (collab) ou em memória (solo)."""
    if settings.is_collab:
        r = redis.from_url(settings.redis_url)
        r.set(f"status:{meeting_id}", status.value, ex=86400)
    else:
        _status_store[meeting_id] = status


def _get_status(meeting_id: str) -> ProcessingStatus | None:
    """Lê status do Redis (collab) ou da memória (solo)."""
    if settings.is_collab:
        r = redis.from_url(settings.redis_url)
        val = r.get(f"status:{meeting_id}")
        if not val:
            return None
        if isinstance(val, (bytes, bytearray)):
            status_str = val.decode()
        else:
            status_str = str(val)
        return ProcessingStatus(status_str)
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
        delay_fn = getattr(process_meeting_task, "delay", None)
        if callable(delay_fn):
            delay_fn(meeting_id, audio_path, title)
        else:
            process_meeting_task(meeting_id, audio_path, title)
    else:
        _process_sync(meeting_id, audio_path, title)

    return UploadResponse(
        meeting_id=meeting_id,
        status=_get_status(meeting_id) or ProcessingStatus.PENDING,
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
    from domain.entities.meeting import Meeting
    from use_cases.transcribe_meeting import TranscribeMeetingInput
    from use_cases.summarize_meeting import SummarizeMeetingInput

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
                         deadline=t.deadline) for t in summary.tasks],
        decisions=[DecisionSchema(description=d.description, context=d.context)
                   for d in summary.decisions],
    )

# Adicione no final de api/routers/meetings.py


@router.post("/bot")
async def send_bot_to_meeting(
    meeting_url: str,
    title: str = "Reunião",
):
    """
    Envia o bot para uma reunião Google Meet.

    O bot entra como participante, grava o áudio e ao encerrar
    processa automaticamente: Whisper → GPT-4o → resumo disponível.
    """
    container = get_container()

    if not hasattr(container, "record_meeting") or not container.record_meeting:
        raise HTTPException(
            400,
            "Bot não configurado. Adicione no .env:\n"
            "  RECORDER_PROVIDER=playwright\n"
            "  BOT_GOOGLE_EMAIL=seubot@gmail.com\n"
            "  BOT_GOOGLE_PASSWORD=senha\n"
            "E execute: python bot_setup.py",
        )

    # Callback executado quando reunião terminar
    def on_meeting_finished(audio_path: str, meeting_title: str) -> None:
        """Processa o áudio assim que o bot sair da reunião."""
        _process_bot_audio(audio_path, meeting_title)

    from use_cases.record_meeting import SendBotInput
    result = container.record_meeting.send_bot(
        SendBotInput(
            meeting_url=meeting_url,
            title=title,
            on_finished=on_meeting_finished,
        )
    )

    if not result.success:
        raise HTTPException(500, f"Erro ao enviar bot: {result.error_message}")

    return {
        "session_id": result.session_id,
        "status": "joining",
        "message": f"Bot enviando para a reunião. Session ID: {result.session_id}",
    }


@router.get("/bot/{session_id}/status")
def get_bot_status(session_id: str):
    """Retorna o status atual do bot em uma reunião."""
    container = get_container()

    if not hasattr(container, "record_meeting") or not container.record_meeting:
        raise HTTPException(400, "Bot não configurado.")

    status = container.record_meeting.get_status(session_id)
    return {
        "session_id": status.session_id,
        "status": status.status,
        "duration_minutes": round(status.duration_seconds / 60, 1),
        "ready": status.status == "done",
    }


def _process_bot_audio(audio_path: str, title: str) -> None:
    """Processa o áudio do bot: transcreve e resume."""
    import uuid
    from datetime import datetime
    from domain.entities.meeting import Meeting
    from use_cases.transcribe_meeting import TranscribeMeetingInput
    from use_cases.summarize_meeting import SummarizeMeetingInput

    container = get_container()
    meeting_id = str(uuid.uuid4())

    _set_status(meeting_id, ProcessingStatus.TRANSCRIBING)

    t = container.transcribe_meeting.execute(
        TranscribeMeetingInput(audio_path=audio_path, with_diarization=True)
    )
    if not t.success:
        _set_status(meeting_id, ProcessingStatus.ERROR)
        return

    meeting = Meeting(
        id=meeting_id,
        title=title,
        started_at=datetime.now(),
        audio_path=audio_path,
        transcript_text=t.transcript.full_text,
        transcript_formatted=t.transcript.formatted,
        participants=t.transcript.speakers,
        duration_minutes=t.transcript.duration_minutes,
    )

    _set_status(meeting_id, ProcessingStatus.SUMMARIZING)
    s = container.summarize_meeting.execute(SummarizeMeetingInput(meeting=meeting))
    _set_status(
        meeting_id,
        ProcessingStatus.DONE if s.success else ProcessingStatus.ERROR,
    )
    print(f"[Bot] ✅ Reunião processada: {title} ({meeting_id})")