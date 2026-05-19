# Use case: responde perguntas sobre reunião com contexto de transcrição
from dataclasses import dataclass, field
from entities.meeting import Meeting
from interface.llm_services import ILLMService, LLMServiceError


# Dados de entrada para chat com reunião
@dataclass
class ChatWithMeetingInput:
    meeting: Meeting  # Reunião para contexto
    question: str  # Pergunta do usuário
    history: list[dict] = field(default_factory=list)  # Histórico: [{"role": "user"|"assistant", "content": str}]


# Dados de saída do chat
@dataclass
class ChatWithMeetingOutput:
    answer: str  # Resposta gerada pela LLM
    success: bool  # Status da operação
    error_message: str = ""


# Use case que recebe LLM service via injeção de dependência
class ChatWithMeetingUC:
    """Orquestra conversa sobre reunião com contexto de transcrição."""

    def __init__(self, llm_service: ILLMService) -> None:
        self._llm = llm_service

    # Executa chat: valida transcrição, passa contexto e histórico para LLM
    def execute(self, input_data: ChatWithMeetingInput) -> ChatWithMeetingOutput:
        meeting = input_data.meeting

        if not meeting.is_transcribed:
            return ChatWithMeetingOutput(
                answer="",
                success=False,
                error_message="Não há transcrição disponível para esta reunião.",
            )

        try:
            context = meeting.transcript_formatted or meeting.transcript_text
            answer = self._llm.chat(
                question=input_data.question,
                context=context,
                history=input_data.history,
            )
            return ChatWithMeetingOutput(answer=answer, success=True)

        except LLMServiceError as e:
            return ChatWithMeetingOutput(
                answer="",
                success=False,
                error_message=str(e),
            )