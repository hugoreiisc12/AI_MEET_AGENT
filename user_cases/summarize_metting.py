# Use case: sumariza reunião transcrita e gera resumo estruturado
from dataclasses import dataclass
from entities.metting import Meeting, Summary
from interface.llm_services import ILLMService, LLMServiceError


# Dados de entrada para sumarização de reunião
@dataclass
class SummarizeMeetingInput:
    meeting: Meeting  # Reunião já transcrita


# Dados de saída da sumarização
@dataclass
class SummarizeMeetingOutput:
    summary: Summary  # Resumo gerado pela LLM
    success: bool  # Status da operação
    error_message: str = "SUMMARIZATION FAILED"


# Use case que recebe LLM service via injeção de dependência
class SummarizeMeetingUC:
    """Orquestra sumarização via LLM com persistência opcional."""

    def __init__(self, llm_service: ILLMService, repository=None) -> None:
        self._llm_service = llm_service
        self._repo = repository

    # Executa sumarização: valida, chama LLM, anexa resumo, persiste
    def execute(self, input_data: SummarizeMeetingInput) -> SummarizeMeetingOutput:
        meeting = input_data.meeting

        if not meeting.is_transcribed:
            return SummarizeMeetingOutput(
                summary=Summary(),
                success=False,
                error_message="Reunião ainda não foi transcrita.",
            )

        try:
            # Usa texto formatado com speakers se disponível
            transcript_for_llm = meeting.transcript_formatted or meeting.transcript_text
            summary: Summary = self._llm_service.summarize(transcript_for_llm)
            meeting.summary = summary

            if self._repo:
                self._repo.save(meeting)

            return SummarizeMeetingOutput(summary=summary, success=True)

        except LLMServiceError as e:
            return SummarizeMeetingOutput(
                summary=Summary(),
                success=False,
                error_message=f"Erro no LLM: {str(e)}",
            )