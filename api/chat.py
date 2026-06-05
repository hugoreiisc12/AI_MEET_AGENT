from fastapi import APIRouter, HTTPException

# FIX: era `from api.meeting import ...` — arquivo não existe.
# FIX: ChatRequest e ChatResponse não estavam importados, causando NameError
#      no response_model= e no type hint do body.
from api.schemas.meeting import ChatRequest, ChatResponse
from use_cases.chat_with_meeting import ChatWithMeetingInput
from presentation.container import get_container

router = APIRouter()


@router.post("/{meeting_id}/chat", response_model=ChatResponse)
def chat(meeting_id: str, body: ChatRequest):
    """Responde pergunta sobre a reunião. Histórico gerenciado pelo cliente."""
    container = get_container()
    meeting = container.repository.find_by_id(meeting_id)

    if not meeting:
        raise HTTPException(404, "Reunião não encontrada")
    if not meeting.is_transcribed:
        raise HTTPException(422, "Reunião ainda não foi transcrita")

    result = container.chat_with_meeting.execute(
        ChatWithMeetingInput(
            meeting=meeting,
            question=body.question,
            history=body.history,
            request_user_id=body.request_user_id,
        )
    )

    if not result.success:
        raise HTTPException(500, result.error_message)

    return ChatResponse(
        answer=result.answer,
        meeting_id=meeting_id,
        identified_user=getattr(result, "identified_user", None),
    )