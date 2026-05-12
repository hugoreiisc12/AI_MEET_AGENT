# Importa FastAPI Router para definir rotas HTTP e schemas de requisição/resposta
from fastapi import APIRouter, HTTPException
from api.schemas.meeting import ChatRequest, ChatResponse
from use_cases.chat_with_meeting import ChatWithMeetingInput
from presentation.container import get_container

# Cria um roteador para as endpoints de chat
router = APIRouter()


# Endpoint POST que processa perguntas sobre uma reunião específica
@router.post("/{meeting_id}/chat", response_model=ChatResponse)
def chat(meeting_id: str, body: ChatRequest):
    """
    Responde pergunta sobre a reunião.
    O histórico de conversa é gerenciado pelo cliente (enviado em cada requisição).
    """
    # Obtém o container com injeção de dependências
    container = get_container()
    # Busca a reunião no repositório pelo ID
    meeting = container.repository.find_by_id(meeting_id)

    # Verifica se a reunião foi encontrada, caso contrário retorna erro 404
    if not meeting:
        raise HTTPException(404, "Reunião não encontrada")
    # Verifica se a reunião foi transcrita, caso contrário retorna erro 422
    if not meeting.is_transcribed:
        raise HTTPException(422, "Reunião ainda não foi transcrita")

    # Executa o caso de uso de chat com a reunião, pergunta e histórico
    result = container.chat_with_meeting.execute(
        ChatWithMeetingInput(
            meeting=meeting,  # Reunião com contexto
            question=body.question,  # Pergunta do usuário
            history=body.history,  # Histórico de conversas anteriores
        )
    )

    # Se houve erro na execução, retorna erro 500 com mensagem
    if not result.success:
        raise HTTPException(500, result.error_message)

    # Retorna a resposta do agente com o ID da reunião
    return ChatResponse(answer=result.answer, meeting_id=meeting_id)