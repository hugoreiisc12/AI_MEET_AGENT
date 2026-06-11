import uuid
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, HTTPException, Body, BackgroundTasks
from collections import Counter
from pydantic import BaseModel, Field
import redis


from api.schemas.meeting import (
    UploadResponse, MeetingStatusResponse, ProcessingStatus,
    SummarySchema, TaskSchema, DecisionSchema,
)
from config.settings import get_settings
from presentation.container import get_container

# FIX: rotas registradas na ordem correta para evitar conflito no FastAPI.
# GET "/" e POST "/bot/done" devem vir ANTES de GET "/{meeting_id}/status",
# caso contrário o FastAPI interpreta "bot" e "done" como meeting_id.
router = APIRouter()
settings = get_settings()

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


# ── Rotas sem path param — DEVEM vir antes de /{meeting_id}/... ──────────

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


# FIX: era `@router.post("/bot")` com `meeting_url: str` como query param.
# URLs do Meet têm caracteres especiais (://, /) que corrompem query strings.
# Agora usa body Pydantic.
class SendBotRequest(BaseModel):
    meeting_url: str
    title: str = "Reunião"


@router.post("/bot")
async def send_bot_to_meeting(body: SendBotRequest):
    """
    Envia o bot para uma reunião Google Meet.
    Recebe meeting_url e title como JSON body (não query params).
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

    from use_cases.record_meeting import SendBotInput
    meeting_id = str(uuid.uuid4())

    def on_meeting_finished(
        audio_path: str,
        meeting_title: str,
        participant_info: dict[str, str],
        speaker_observations: list[dict[str, float | str]],
        mid: str,
    ) -> None:
        _process_bot_audio(
            mid,
            audio_path,
            meeting_title,
            participant_info,
            speaker_observations,
        )

    result = container.record_meeting.send_bot(
        SendBotInput(
            meeting_url=body.meeting_url,
            title=body.title,
            meeting_id=meeting_id,
            on_finished=on_meeting_finished,
        )
    )

    if not result.success:
        raise HTTPException(500, f"Erro ao enviar bot: {result.error_message}")

    return {
        "session_id": result.session_id,
        "status": "joining",
        "message": f"Bot enviado para a reunião. Session ID: {result.session_id}",
    }


# FIX: endpoint que o app.py chama via on_done (antes apontava para /bot-done
# que não existia em nenhum router)
class BotDoneRequest(BaseModel):
    meeting_id: str = ""
    audio_path: str
    title: str = "Reunião"
    participant_info: dict[str, str] = Field(default_factory=dict)
    speaker_observations: list[dict[str, float | str]] = Field(default_factory=list)


@router.post("/bot/done")
async def bot_done(body: BotDoneRequest, background_tasks: BackgroundTasks):
    """
    Chamado pelo callback on_done do Streamlit quando o bot termina a reunião.
    Dispara o processamento (transcrição + resumo) do áudio gravado em background.
    """
    meeting_id = body.meeting_id or str(uuid.uuid4())
    background_tasks.add_task(
        _process_bot_audio,
        meeting_id,
        body.audio_path,
        body.title,
        body.participant_info,
        body.speaker_observations,
    )
    return {"status": "processing", "message": f"Processamento iniciado. ID: {meeting_id}"}


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
        "ready": status.status == "done",
    }


# ── Rotas com path param — DEVEM vir depois das rotas fixas ──────────────

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


# ── Helpers ───────────────────────────────────────────────────────────────

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

    if s_result.success:
        meeting.summary = s_result.summary
        container.repository.save(meeting)

    _set_status(
        meeting_id,
        ProcessingStatus.DONE if s_result.success else ProcessingStatus.ERROR,
    )


def _process_bot_audio(
    meeting_id: str,
    audio_path: str,
    title: str,
    participant_info: dict[str, str] | None = None,
    speaker_observations: list[dict[str, float | str]] | None = None,
) -> None:
    """Dispara o pipeline completo (transcrever → sumarizar → salvar)."""
    container = get_container()

    container.pipeline_orchestrator.run_pipeline(
        meeting_id=meeting_id,
        audio_path=audio_path,
        title=title,
        participant_info=participant_info or {},
        speaker_observations=speaker_observations or [],
    )

    _set_status(meeting_id, ProcessingStatus.PENDING)
    print(f"[Bot] ✅ Pipeline disparado: {title} ({meeting_id})")


def _infer_speaker_aliases(
    transcript,
    participant_info: dict[str, str] | None,
    speaker_observations: list[dict[str, float | str]] | None,
) -> dict[str, str]:
    """Infer speaker ID -> email/nome usando amostras de speaker ativo e timestamps."""
    if not transcript.segments or not participant_info or not speaker_observations:
        return {}

    speaker_counts: dict[str, Counter[str]] = {}

    for observation in speaker_observations:
        timestamp = observation.get("timestamp")
        participant_id = observation.get("participant_id")
        if timestamp is None or not participant_id or not isinstance(participant_id, str):
            continue

        try:
            timestamp = float(timestamp)
        except Exception:
            continue

        for segment in transcript.segments:
            if segment.start <= timestamp < segment.end:
                counts = speaker_counts.setdefault(segment.speaker, Counter())
                counts[participant_id] += 1
                break

    mapping: dict[str, str] = {}
    for speaker, counts in speaker_counts.items():
        if not counts:
            continue
        best_participant = max(counts.items(), key=lambda item: item[1])[0]
        mapping[speaker] = participant_info.get(best_participant) or best_participant

    if not mapping and len(transcript.speakers) == 1 and len(participant_info) == 1:
        only_person = next(iter(participant_info.values()))
        mapping[transcript.speakers[0]] = only_person

    return mapping


def _map_summary(summary) -> SummarySchema:
    # FIX: era `from api.meeting import ...` — arquivo não existe
    # Imports já estão no topo do arquivo via api.schemas.meeting
    return SummarySchema(
        overview=summary.overview,
        topics=summary.topics,
        tasks=[
            TaskSchema(
                description=t.description,
                responsible=t.responsible,
                deadline=t.deadline,
            )
            for t in summary.tasks
        ],
        decisions=[
            DecisionSchema(description=d.description, context=d.context)
            for d in summary.decisions
        ],
    )