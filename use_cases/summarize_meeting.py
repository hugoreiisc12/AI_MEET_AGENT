# Use case: sumariza reunião transcrita e gera resumo estruturado
from dataclasses import dataclass
from typing import Optional
from domain.entities.meeting import Meeting, Summary
from domain.entities.meeting_type import MeetingType
from interface.llm_services import ILLMService, LLMServiceError


# Dados de entrada para sumarização de reunião
@dataclass
class SummarizeMeetingInput:
    meeting: Meeting
    meeting_type: MeetingType = MeetingType.GENERAL


# Dados de saída da sumarização
@dataclass
class SummarizeMeetingOutput:
    success: bool
    summary: Optional[Summary] = None
    meeting: Optional[Meeting] = None
    error_message: str = ""


class SummarizeMeetingUC:
    """Orquestra sumarização via LLM com persistência opcional."""

    def __init__(self, llm_service: ILLMService, repository=None) -> None:
        self._llm_service = llm_service
        self._repo = repository

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
            transcript_for_llm = meeting.transcript_formatted or meeting.transcript_text
            summary: Summary = self._llm_service.summarize(
                transcript_for_llm,
                input_data.meeting_type,
            )
            meeting.summary = summary

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