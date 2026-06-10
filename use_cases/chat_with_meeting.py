import re
from dataclasses import dataclass, field
from domain.entities.meeting import Meeting
from interface.llm_services import ILLMService, LLMServiceError


# Dados de entrada para chat com reunião
@dataclass
class ChatWithMeetingInput:
    meeting: Meeting  # Reunião para contexto
    question: str  # Pergunta do usuário
    history: list[dict] = field(default_factory=list)  # Histórico: [{"role": "user"|"assistant", "content": str}]
    request_user_id: str | None = None


# Dados de saída do chat
@dataclass
class ChatWithMeetingOutput:
    answer: str  # Resposta gerada pela LLM
    success: bool  # Status da operação
    error_message: str = ""
    identified_user: str | None = None
    task_data: dict | None = None  # Dados da tarefa extraída, se houver


TASK_MARKER_RE = re.compile(
    r"---TAREFA---\s*\n?(\{.*?\})\n?\[/TAREFA\]",
    re.DOTALL,
)


def _parse_task_from_response(response: str) -> tuple[str, dict | None]:
    """Extrai marcador de tarefa da resposta e retorna (resposta_limpa, task_data)."""
    import json
    match = TASK_MARKER_RE.search(response)
    if not match:
        return response, None
    raw_json = match.group(1).strip()
    try:
        task_data = json.loads(raw_json)
    except json.JSONDecodeError:
        return response, None
    clean = TASK_MARKER_RE.sub("", response).strip()
    return clean, task_data


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
            summary_context = meeting.summary.formatted if meeting.summary else ""
            identified_user = meeting.identify_user(input_data.request_user_id)
            raw_answer = self._llm.chat(
                question=input_data.question,
                context=context,
                history=input_data.history,
                summary_context=summary_context,
                user_id=identified_user,
            )
            clean_answer, task_data = _parse_task_from_response(raw_answer)
            return ChatWithMeetingOutput(
                answer=clean_answer,
                success=True,
                identified_user=identified_user,
                task_data=task_data,
            )

        except LLMServiceError as e:
            return ChatWithMeetingOutput(
                answer="",
                success=False,
                error_message=str(e),
            )