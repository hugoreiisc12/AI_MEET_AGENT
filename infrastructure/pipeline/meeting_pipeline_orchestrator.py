import threading
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from domain.entities.meeting import Meeting
from use_cases.summarize_meeting import SummarizeMeetingUC, SummarizeMeetingInput

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    success: bool
    meeting_id: str
    error: str = ""
    meeting: Optional[Meeting] = None


class MeetingPipelineOrchestrator:
    """Orquestra o pipeline de processamento de reuniões em background.
    
    O status de cada reunião é derivado diretamente do estado dos dados
    no repositório (Direct Query), sem necessidade de tracking em memória.
    """

    def __init__(
        self,
        repository,
        transcribe_uc,
        summarize_uc: SummarizeMeetingUC,
        block_transcriber=None,
        chat_uc=None,
    ) -> None:
        self._repository = repository
        self._transcribe_uc = transcribe_uc
        self._summarize_uc = summarize_uc
        self._block_transcriber = block_transcriber
        self._chat_uc = chat_uc

    # ── Pipeline principal ────────────────────────────────────────────────

    def run_pipeline(
        self,
        meeting_id: str,
        audio_path: str,
        title: str,
        participant_info: dict[str, str] | None = None,
        speaker_observations: list[dict] | None = None,
    ) -> PipelineResult:
        """
        Executa o pipeline completo em background:
        validar áudio → transcrever → sumarizar → salvar.
        O status é derivado automaticamente pelo save() em cada etapa.
        """
        thread = threading.Thread(
            target=self._execute_pipeline,
            args=(meeting_id, audio_path, title, participant_info or {}, speaker_observations or []),
            daemon=True,
            name=f"Pipeline-{meeting_id[:8]}",
        )
        thread.start()
        return PipelineResult(success=True, meeting_id=meeting_id)

    # ── Execução interna (roda na thread) ─────────────────────────────────

    def _execute_pipeline(
        self,
        meeting_id: str,
        audio_path: str,
        title: str,
        participant_info: dict[str, str],
        speaker_observations: list[dict],
    ) -> None:
        try:
            # ── 0. Validar LLM e componentes do pipeline ────────────────────
            logger.info("[Pipeline] Passo 0/5 — Validando componentes do pipeline")
            validation = self._validate_components()
            if not validation["ok"]:
                logger.error("[Pipeline] ❌ Componentes com falha: %s", validation["errors"])
                return

            # ── 1. Validar arquivo de áudio ────────────────────────────────
            logger.info("[Pipeline] Passo 1/5 — Validando áudio: %s", audio_path)
            if not self._validate_audio(audio_path):
                logger.error("[Pipeline] ❌ Áudio não encontrado: %s", audio_path)
                return

            # ── 2. Criar e salvar reunião (status → "pending") ──────────────
            logger.info("[Pipeline] Passo 2/5 — Salvando reunião: %s", meeting_id)
            meeting = self._create_meeting(
                meeting_id, title, audio_path,
                participant_info, speaker_observations,
            )
            self._repository.save(meeting)

            # ── 3. Transcrever (status → "transcribing" no save) ────────────
            logger.info("[Pipeline] Passo 3/5 — Transcrevendo: %s", meeting_id)
            self._transcribe(meeting)
            if not meeting.transcript_text:
                logger.error("[Pipeline] ❌ Transcrição falhou: %s", meeting_id)
                return
            self._repository.save(meeting)
            logger.info("[Pipeline] ✅ Transcrição concluída: %s", meeting_id)

            # ── 4. Sumarizar (status → "done" no save) ──────────────────────
            logger.info("[Pipeline] Passo 4/5 — Sumarizando: %s", meeting_id)
            self._summarize(meeting)
            if not meeting.is_summarized:
                logger.error("[Pipeline] ❌ Sumarização falhou: %s", meeting_id)
                return
            self._repository.save(meeting)
            logger.info("[Pipeline] ✅ Sumarização concluída: %s", meeting_id)

            # ── 5. Finalizar ────────────────────────────────────────────────
            logger.info("[Pipeline] Passo 5/5 — Pipeline completo: %s — %s", meeting_id, title)

        except Exception as exc:
            logger.exception("[Pipeline] ❌ Erro no pipeline %s: %s", meeting_id, exc)

    # ── Passos individuais ────────────────────────────────────────────────

    @staticmethod
    def _validate_audio(audio_path: str) -> bool:
        return bool(audio_path) and Path(audio_path).exists()

    @staticmethod
    def _create_meeting(
        meeting_id: str,
        title: str,
        audio_path: str,
        participant_info: dict[str, str],
        speaker_observations: list[dict],
    ) -> Meeting:
        return Meeting(
            id=meeting_id,
            title=title,
            started_at=datetime.now(),
            audio_path=audio_path,
            participant_info=participant_info,
            speaker_observations=speaker_observations,
        )

    def _transcribe(self, meeting: Meeting) -> None:
        has_observations = bool(meeting.speaker_observations) and bool(meeting.participant_info)

        if has_observations and self._block_transcriber is not None:
            blocks = self._block_transcriber.transcribe_blocks(
                meeting.audio_path,
                meeting.speaker_observations,
                meeting.participant_info,
            )
            if not blocks:
                return

            data = self._block_transcriber.blocks_to_transcript_data(blocks)
            meeting.transcript_text = data["full_text"]
            meeting.transcript_formatted = data["formatted"]
            meeting.speech_blocks = blocks
            meeting.duration_minutes = data["duration_minutes"]
            participants = list(dict.fromkeys(meeting.participant_info.values()))
            meeting.participants = participants or data["speakers"]
        else:
            from use_cases.transcribe_meeting import TranscribeMeetingInput

            result = self._transcribe_uc.execute(
                TranscribeMeetingInput(audio_path=meeting.audio_path, with_diarization=True)
            )
            if result.success:
                meeting.transcript_text = result.transcript.full_text
                meeting.transcript_formatted = result.transcript.formatted
                meeting.participants = result.transcript.speakers
                meeting.duration_minutes = result.transcript.duration_minutes

    def _summarize(self, meeting: Meeting) -> None:
        result = self._summarize_uc.execute(SummarizeMeetingInput(meeting=meeting))
        if result.success:
            meeting.summary = result.summary

    # ── Validação ─────────────────────────────────────────────────────────

    def _validate_components(self) -> dict:
        errors = []
        if self._transcribe_uc is None:
            errors.append("TranscribeUC não configurado")
        if self._summarize_uc is None:
            errors.append("SummarizeUC não configurado")
        if self._repository is None:
            errors.append("Repository não configurado")

        return {"ok": len(errors) == 0, "errors": "; ".join(errors)}

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def get_pipeline_status(meeting: Meeting) -> str:
        """Deriva o status do pipeline a partir do estado da reunião."""
        if meeting.is_summarized:
            return "done"
        if meeting.is_transcribed:
            return "transcribing"
        if meeting.audio_path:
            return "pending"
        return "error"
