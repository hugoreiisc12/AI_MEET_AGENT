"""Pipeline único de processamento: áudio → transcrição → resumo. Ver ADR-001."""
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from domain.entities.meeting import Meeting, MeetingStatus
from domain.entities.meeting_type import MeetingType
from domain.interfaces.meeting_repository import IMeetingRepository
from use_cases.speaker_alignment import SpeakerEvents, assign_speakers
from use_cases.summarize_meeting import SummarizeMeetingInput, SummarizeMeetingUC
from use_cases.transcribe_meeting import TranscribeMeetingInput, TranscribeMeetingUC

logger = logging.getLogger(__name__)


@dataclass
class ProcessMeetingInput:
    meeting_id: str
    audio_path: str
    title: str
    meeting_type: MeetingType = MeetingType.GENERAL
    with_diarization: bool = True


class ProcessMeetingUC:
    """Grava o status no repositório a cada etapa. Idempotente por meeting_id:
    reprocessar o mesmo id sobrescreve o mesmo documento."""

    def __init__(
        self,
        transcribe_uc: TranscribeMeetingUC,
        summarize_uc: SummarizeMeetingUC,
        repository: IMeetingRepository,
        load_speaker_events: Optional[Callable[[str], SpeakerEvents]] = None,
        indexer=None,
    ) -> None:
        self._indexer = indexer  # memória do agente (ADR-022): trechos e entidades da reunião pronta
        self._transcribe = transcribe_uc
        self._summarize = summarize_uc
        self._repo = repository
        self._load_speaker_events = load_speaker_events

    def execute(self, data: ProcessMeetingInput) -> Meeting:
        """As duas etapas em sequência (modo solo e CLI)."""
        meeting = self.transcribe(data)
        if meeting.status is MeetingStatus.ERROR:
            return meeting
        return self.summarize(meeting.id, data.meeting_type)

    def transcribe(self, data: ProcessMeetingInput) -> Meeting:
        """Etapa 1 (fila "transcribe"): termina com status summarizing, à espera do LLM."""
        meeting = self._repo.find_by_id(data.meeting_id) or Meeting(id=data.meeting_id, title=data.title)
        meeting.title = data.title or meeting.title
        meeting.audio_path = data.audio_path
        return self._guard(meeting, self._transcribe_stage, meeting, data)

    def summarize(self, meeting_id: str, meeting_type: MeetingType = MeetingType.GENERAL) -> Meeting:
        """Etapa 2 (fila "llm"): resumo de uma reunião já transcrita."""
        meeting = self._repo.find_by_id(meeting_id)
        if meeting is None:
            raise LookupError(f"Reunião {meeting_id} não existe")
        if not meeting.is_transcribed:
            return self._fail(meeting, "Resumo pedido antes da transcrição.")
        return self._guard(meeting, self._summarize_stage, meeting, meeting_type)

    def _guard(self, meeting: Meeting, stage, *args) -> Meeting:
        try:
            return stage(*args)
        except Exception as exc:
            logger.exception("[%s] falha inesperada no processamento", meeting.id)
            return self._fail(meeting, f"Erro inesperado: {exc}")

    def _transcribe_stage(self, meeting: Meeting, data: ProcessMeetingInput) -> Meeting:
        audio = Path(data.audio_path)
        if not audio.exists() or audio.stat().st_size == 0:
            return self._fail(meeting, f"Áudio ausente ou vazio: {data.audio_path}")

        self._set(meeting, MeetingStatus.TRANSCRIBING)
        t0 = time.monotonic()
        t = self._transcribe.execute(
            TranscribeMeetingInput(audio_path=data.audio_path, with_diarization=data.with_diarization)
        )
        if not t.success:
            return self._fail(meeting, t.error_message)
        if not t.transcript.full_text.strip():
            return self._fail(meeting, "Transcrição vazia: nenhum trecho de fala reconhecido.")

        # Nomes reais, quando o bot registrou quem falou (ADR-009 fase 2).
        events = self._load_speaker_events(data.audio_path) if self._load_speaker_events else SpeakerEvents()
        named = assign_speakers(t.transcript.segments, events)
        if events.participants:
            logger.info("[%s] %d participantes; %d/%d segmentos com nome",
                        meeting.id, len(events.participants), named, len(t.transcript.segments))

        meeting.transcript_text = t.transcript.full_text
        meeting.transcript_formatted = t.transcript.formatted
        meeting.transcript_raw = t.transcript.text_raw
        meeting.participants = events.participants or t.transcript.speakers
        meeting.duration_minutes = t.transcript.duration_minutes

        # Medições para dimensionar o contexto do LLM (ADR-010).
        meeting.metrics = {
            "transcribe_s": round(time.monotonic() - t0, 1),
            "transcript_chars": len(meeting.transcript_for_llm),
        }
        self._set(meeting, MeetingStatus.SUMMARIZING)
        return meeting

    def _summarize_stage(self, meeting: Meeting, meeting_type: MeetingType) -> Meeting:
        self._set(meeting, MeetingStatus.SUMMARIZING)
        t1 = time.monotonic()
        s = self._summarize.execute(SummarizeMeetingInput(meeting=meeting, meeting_type=meeting_type))
        if not s.success:
            return self._fail(meeting, s.error_message)

        meeting.summary = s.summary
        meeting.metrics["summarize_s"] = round(time.monotonic() - t1, 1)
        logger.info("[%s] medições: %s", meeting.id, meeting.metrics)
        self._set(meeting, MeetingStatus.DONE)
        if self._indexer:
            self._indexer.index(meeting)  # não falha: sem índice, o chat busca por palavra
        return meeting

    def _set(self, meeting: Meeting, status: MeetingStatus) -> None:
        meeting.status = status
        meeting.error = ""
        meeting.queue = ""  # um worker pegou a reunião: saiu da fila
        self._repo.save(meeting)
        logger.info("[%s] status=%s", meeting.id, status.value)

    def _fail(self, meeting: Meeting, error: str) -> Meeting:
        meeting.status = MeetingStatus.ERROR
        meeting.error = error
        meeting.queue = ""
        self._repo.save(meeting)
        logger.error("[%s] %s", meeting.id, error)
        return meeting
