from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from domain.entities.meeting import MeetingStatus


class TaskSchema(BaseModel):
    description: str
    responsible: str
    deadline: Optional[str] = None
    done: bool = False


class DecisionSchema(BaseModel):
    description: str
    context: str = ""
    status: str = Field("", description="aprovada, condicionada, proposta, pendente, rejeitada ou inconclusiva; "
                                        "vazio em resumos anteriores ao contrato do agente")


class ContributionSchema(BaseModel):
    speaker: str
    points: list[str]


class TopicDecisionSchema(BaseModel):
    topic: str
    decision: str
    effect: str = ""


class SummarySchema(BaseModel):
    overview: str
    topics: list[str]
    tasks: list[TaskSchema]
    decisions: list[DecisionSchema]
    contributions: list[ContributionSchema] = []
    topic_decisions: list[TopicDecisionSchema] = []
    open_questions: list[str] = []


class AttachmentSchema(BaseModel):
    id: str
    format: str
    filename: str


class ChatActionSchema(BaseModel):
    """Ação que o agente preparou no chat. E-mail: `pending` até POST .../send ou .../cancel.
    Documento: `created`, baixar em GET .../document. Memória: nota guardada (`title` = a nota),
    ver e apagar em /memory."""
    id: str
    type: Literal["email", "document", "memory"]
    status: Literal["pending", "sent", "canceled", "created"]
    to: list[str] = []
    subject: str = ""
    body: str = ""
    format: str = Field("", description="pdf, docx, xlsx, csv, html ou md (documento)")
    title: str = ""
    filename: str = ""
    sent_at: str = ""
    attachments: list[AttachmentSchema] = Field([], description="Arquivos anexados ao e-mail")


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    action: Optional[ChatActionSchema] = None


class MeetingStatusResponse(BaseModel):
    meeting_id: str
    status: MeetingStatus = Field(description="pending → recording → transcribing → summarizing → done | error")
    error: str = Field("", description="Motivo, quando status = error")
    title: str
    platform: str = Field("", description="meet, teams ou zoom; vazio para áudio enviado")
    started_at: datetime
    duration_minutes: float = 0.0
    participants: list[str] = []
    summary: Optional[SummarySchema] = Field(None, description="Ausente na listagem e enquanto não houver resumo")
    queue_position: int = Field(0, description="Só em GET /meetings/{id}/status: posição na fila da etapa atual "
                                               "(1 = é a próxima; 0 = não está esperando)")
    stage_elapsed_s: Optional[float] = Field(None, description="Só em /status: segundos desde que a etapa atual começou")
    stage_typical_s: Optional[float] = Field(None, description="Só em /status: quanto essa etapa costuma levar (mediana)")
    stalled: bool = Field(False, description="Só em /status: a etapa parou (nenhum worker com a reunião, fora da fila); "
                                             "retome com POST /meetings/{id}/resume")


class MeetingDetailResponse(MeetingStatusResponse):
    transcript: str = Field("", description="Transcrição com o nome de quem falou em cada trecho")
    chat_history: list[ChatMessage] = []
    has_audio: bool = Field(False, description="Há gravação em disco: a reunião pode ser reprocessada")


class UploadResponse(BaseModel):
    meeting_id: str
    status: MeetingStatus
    message: str


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, examples=["Quais tarefas ficaram com a Maria?"])
    history: Optional[list[ChatMessage]] = Field(
        None, description="Omitido (recomendado) = usa e atualiza a conversa guardada na reunião.",
    )


class ChatResponse(BaseModel):
    answer: str
    meeting_id: str
    action: Optional[ChatActionSchema] = Field(
        None, description="Presente quando o pedido foi uma ação: e-mail para confirmar ou documento gerado")


class PlatformSchema(BaseModel):
    key: str
    label: str
    example: str = Field(description="Formato de link aceito")
    validated: bool = Field(description="Falso = suporte ainda não validado em reunião real")
    speaker_names: bool = Field(description="A transcrição traz o nome de quem falou")


class ConfigResponse(BaseModel):
    mode: str = Field(description="solo ou collab: modo em que esta API está rodando")
    login_enabled: bool = Field(description="Sempre verdadeiro: há login nos dois modos (JSON no solo, MongoDB no collab)")
    registration_open: bool
    email_enabled: bool = Field(description="POST /meetings/{id}/tasks/email disponível")
    calendar_enabled: bool = Field(description="Título do bot pode ser omitido: vem da agenda")
    max_upload_mb: int
    audio_formats: list[str]
    platforms: list[PlatformSchema]
