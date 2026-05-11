# Use case para chat com reunião, que recebe uma pergunta e retorna resposta do LLM, mantendo o historico de conversa para contexto adicional.
from dataclasses import dataclass, field
from entities.metting import Meeting  # CORRIGIDO: domain.entities → entities
from interface.llm_services import ILLMService, LLMServiceError  # CORRIGIDO: domain.interfaces → interface


# Definindo classe de dados de entrada para o processo de chat com reunião, que inclui a reunião, a pergunta do usuário e o histórico de mensagens para contexto adicional 
@dataclass
class ChatWithMeetingInput:
    meeting: Meeting
    question: str
    history: list[dict] = field(default_factory=list)
    # history: [{"role": "user"|"assistant", "content": str}]


# Defindo classe de dados de saida para o processo de chat com reunião, que inclui a resposta do LLM, status de sucesso e mensagem de erro se houver falha 
@dataclass
class ChatWithMeetingOutput:
    answer: str
    success: bool
    error_message: str = ""

# Definindo classe para o processo de chat com reunião, que recebe a pergunta do usuário, o contexto da reunião 
class ChatWithMeetingUC:
    """
    Use case: recebe uma pergunta sobre a reunião e retorna resposta do LLM.
    Mantém o histórico de conversa externamente (no Streamlit via session_state).
    """
# Metodo construtor que recebe o serviço de LLM via injeção de dependência, garantindo a indenpendência 
# do domain em relação á implementação especial 
    def __init__(self, llm_service: ILLMService) -> None:
        self._llm = llm_service

# Metodo de execução do processo de chat com reunião, que verifica se a reunião foi transcrita, 
# delega o chat para LLM, passando a pergunta, o contexto da reunião (transcrição) e o histórico de mensagens com tratamento ativo de erros relacionados á LLM
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