# Importa Pydantic para validação de dados e Enum para estados
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from enum import Enum


# Enum que define os possíveis estados de processamento de uma reunião
class ProcessingStatus(str, Enum):
    PENDING = "pending"  # Aguardando processamento
    TRANSCRIBING = "transcribing"  # Transcrevendo o áudio
    SUMMARIZING = "summarizing"  # Gerando resumo
    DONE = "done"  # Processamento concluído
    ERROR = "error"  # Erro durante o processamento


# Schema Pydantic para representar uma tarefa
class TaskSchema(BaseModel):
    description: str  # Descrição da tarefa
    responsible: str  # Pessoa responsável
    deadline: str  # Prazo para conclusão
    done: bool = False  # Status de conclusão (padrão: não concluído)


# Schema Pydantic para representar uma decisão
class DecisionSchema(BaseModel):
    description: str  # Descrição da decisão
    context: str = ""  # Contexto ou motivo (padrão: vazio)


# Schema Pydantic para resumo estruturado da reunião
class SummarySchema(BaseModel):
    overview: str  # Resumo geral da reunião
    topics: list[str]  # Lista de tópicos discutidos
    tasks: list[TaskSchema]  # Tarefas identificadas
    decisions: list[DecisionSchema]  # Decisões tomadas


# Schema para resposta de status de uma reunião
class MeetingStatusResponse(BaseModel):
    meeting_id: str  # ID único da reunião
    status: ProcessingStatus  # Status do processamento
    title: str  # Título da reunião
    started_at: datetime  # Data/hora de início
    duration_minutes: float = 0.0  # Duração em minutos (padrão: 0)
    participants: list[str] = []  # Lista de participantes (padrão: vazia)
    summary: Optional[SummarySchema] = None  # Resumo se disponível


# Schema para resposta após upload de áudio
class UploadResponse(BaseModel):
    meeting_id: str  # ID da reunião criada
    status: ProcessingStatus  # Status inicial do processamento
    message: str  # Mensagem de confirmação


# Schema para requisição de chat
class ChatRequest(BaseModel):
    question: str  # Pergunta do usuário
    history: list[dict] = []  # Histórico de conversa (padrão: vazio)


# Schema para resposta de chat
class ChatResponse(BaseModel):
    answer: str  # Resposta do agente
    meeting_id: str  # ID da reunião em questão