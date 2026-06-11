from dataclasses import dataclass, field
from domain.entities.meeting import Meeting, Task
from interface.llm_services import ILLMService, LLMServiceError


@dataclass
class ChatWithMeetingInput:
    meeting: Meeting
    question: str
    history: list[dict] = field(default_factory=list)


@dataclass
class ChatWithMeetingOutput:
    answer: str
    success: bool
    error_message: str = ""
    extracted_tasks: list[Task] = field(default_factory=list)


class ChatWithMeetingUC:
    """Orquestra conversa sobre reunião com contexto de transcrição."""

    def __init__(self, llm_service: ILLMService) -> None:
        self._llm = llm_service

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
