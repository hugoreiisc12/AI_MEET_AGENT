#  Essea implementação do Use case que recebe uma Meeting já transcrita, gera e anexa o Summary a ela.
from dataclasses import dataclass
from entities.metting import Meeting, Summary  # CORRIGIDO: domain.entities → entities, Metting → Meeting
from interface.llm_services import ILLMService, LLMServiceError  # CORRIGIDO: domain.interfaces → interface

# Definindo os dados de entrada para sumarização de reunião, que recebe uma Meeting já transcrita 
@dataclass 
class SummarizeMeetingInput:  
    meeting: Meeting 

# Definindo os dados de saida do processo de sumarização, que inclui o resumo gerado, status de sucesso e mensagem de erro se houver falha
@dataclass
class SummarizeMeetingOutput:  
    summary: Summary
    success: bool
    error_message: str = "SUMMARIZATION FAILED"


# Criação de classe construtora que recebe o serviço da LLM via injeção de dependência e opcionalmente um repositório para persistência da reunião com o resumo anexado
class SummarizeMeetingUC:
    """ Use case: recebe uma Meeting já transcrita, gera e anexa o Summary a ela.
    Persiste via repositório se fornecido."""

# Definindo o construtor que recebe o serviço da LLM via injeção de dependencia e opcionalmente um repositório para persistência 
    def __init__(
            self, 
            llm_service: ILLMService,
            repository = None
    ) -> None:
        self._llm_service = llm_service
        self._repo = repository

# Metodo de execução do processo de summarização, que verifica se a reunião foi transcrita, delega a sumarização para a LLM, anexa o resumo gerado à reunião 
# e persiste a reunião atualizada se um repositório foi fornecido. Captura ativamente erros relacionados à LLM e retorna mensagens de erro apropriadas.
    def execute(self, input_data: SummarizeMeetingInput) -> SummarizeMeetingOutput:  # CORRIGIDO: typo no tipo de retorno
        meeting = input_data.meeting  # CORRIGIDO: faltava extrair meeting do input_data
        # CORRIGIDO: indentação do if
        if not meeting.is_transcribed:
            return SummarizeMeetingOutput(
                summary=Summary(),  # CORRIGIDO: meeting → summary
                success=False,
                error_message="Reunião ainda não foi transcrita. Execute TranscribeMeetingUC primeiro.",
            )

        try:
            # Prefere o texto formatado (com speakers) se disponível
            transcript_for_llm = meeting.transcript_formatted or meeting.transcript_text
            summary: Summary = self._llm_service.summarize(transcript_for_llm)
            meeting.summary = summary
 
            if self._repo:
                self._repo.save(meeting)

            return SummarizeMeetingOutput(summary=summary, success=True)  # CORRIGIDO: meeting → summary

        except LLMServiceError as e:
            return SummarizeMeetingOutput(
                summary=Summary(),  # CORRIGIDO: meeting → summary
                success=False,
                error_message=f"Erro no LLM: {str(e)}",
            )
 