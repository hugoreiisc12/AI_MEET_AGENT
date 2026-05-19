from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from enum import Enum


class ProcessingStatus(str, Enum):
    PENDING = "pending"
    TRANSCRIBING = "transcribing"
    SUMMARIZING = "summarizing"
    DONE = "done"
    ERROR = "error"


class TaskSchema(BaseModel):
    description: str
    responsible: str
    deadline: Optional[str] = None


class DecisionSchema(BaseModel):
    description: str
    context: str = ""


class SummarySchema(BaseModel):
    overview: str
    topics: list[str]
    tasks: list[TaskSchema]
    decisions: list[DecisionSchema]


class MeetingStatusResponse(BaseModel):
    meeting_id: str
    status: ProcessingStatus
    title: str
    started_at: datetime
    duration_minutes: float = 0.0
    participants: list[str] = []
    summary: Optional[SummarySchema] = None


class UploadResponse(BaseModel):
    meeting_id: str
    status: ProcessingStatus
    message: str


class ChatRequest(BaseModel):
    question: str
    history: list[dict] = []


class ChatResponse(BaseModel):
    answer: str
    meeting_id: str