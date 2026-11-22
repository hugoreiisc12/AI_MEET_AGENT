# Use case: sumariza reunião transcrita e gera resumo estruturado
import logging
from dataclasses import dataclass
from typing import Optional

from domain.entities.meeting import Meeting, Summary
from domain.entities.meeting_type import MeetingType
from domain.interfaces.llm_service import ILLMService, LLMServiceError
from use_cases.llm_context import split_by_lines

logger = logging.getLogger(__name__)


@dataclass
class SummarizeMeetingInput:
    meeting: Meeting
    meeting_type: MeetingType = MeetingType.GENERAL


@dataclass
class SummarizeMeetingOutput:
    success: bool
    summary: Optional[Summary] = None
    meeting: Optional[Meeting] = None
    error_message: str = ""


class SummarizeMeetingUC:
    """Resume a reunião. Transcrição que não cabe num pedido ao LLM é resumida
    em partes e depois reunida (ADR-010)."""

    def __init__(self, llm_service: ILLMService, repository=None, max_context_chars: int = 30000) -> None:
        self._llm_service = llm_service
        self._repo = repository
        self._max_chars = max_context_chars

    def execute(self, input_data: SummarizeMeetingInput) -> SummarizeMeetingOutput:
        meeting = input_data.meeting

        if not meeting.is_transcribed:
            return SummarizeMeetingOutput(
                success=False,
                summary=Summary(),
                meeting=meeting,
                error_message="Reunião ainda não foi transcrita.",
            )

        try:
            header = meeting.participants_header
            parts = split_by_lines(meeting.transcript_formatted or meeting.transcript_text, self._max_chars)
            if len(parts) > 1:
                logger.info("Transcrição longa: resumo em %d partes", len(parts))
            partials = [
                self._llm_service.summarize(
                    header + (f"(Parte {i} de {len(parts)} da reunião)\n" if len(parts) > 1 else "") + part,
                    input_data.meeting_type,
                )
                for i, part in enumerate(parts, 1)
            ]
            summary = partials[0] if len(partials) == 1 else _merge(partials)
            meeting.summary = summary
            meeting.metrics["llm_parts"] = len(parts)

            if self._repo:
                self._repo.save(meeting)

            return SummarizeMeetingOutput(success=True, summary=summary, meeting=meeting)

        except LLMServiceError as e:
            return SummarizeMeetingOutput(
                success=False,
                summary=Summary(),
                meeting=meeting,
                error_message=f"Erro no LLM: {str(e)}",
            )


def _merge(partials: list[Summary]) -> Summary:
    """Junta os resumos das partes na ordem da reunião.

    ponytail: a visão geral é a sequência das visões parciais e tarefas iguais
    citadas em partes diferentes não são fundidas; acrescentar uma chamada de
    consolidação ao LLM se isso incomodar em reuniões longas.
    """
    return Summary(
        overview="\n\n".join(p.overview.strip() for p in partials if p.overview.strip()),
        topics=list(dict.fromkeys(t for p in partials for t in p.topics)),
        tasks=[t for p in partials for t in p.tasks],
        decisions=[d for p in partials for d in p.decisions],
        contributions=_merge_contributions(partials),
        topic_decisions=[t for p in partials for t in p.topic_decisions],
        open_questions=list(dict.fromkeys(q for p in partials for q in p.open_questions)),
    )


def _merge_contributions(partials: list[Summary]) -> list[dict]:
    by_speaker: dict[str, list[str]] = {}
    for p in partials:
        for c in p.contributions:
            by_speaker.setdefault(c["speaker"], []).extend(c["points"])
    return [{"speaker": s, "points": points} for s, points in by_speaker.items()]
