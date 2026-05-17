from fastapi import APIRouter, HTTPException
from api.meeting import ChatRequest, ChatResponse
from user_cases.chat_with_meeting import ChatWithMeetingInput
from presetation.container import get_container

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
        )
    )

    if not result.success:
        raise HTTPException(500, result.error_message)

    return ChatResponse(answer=result.answer, meeting_id=meeting_id)