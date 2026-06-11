from datetime import datetime
from typing import Optional
from beanie import Document
from pydantic import BaseModel, Field


class TaskEmbedded(BaseModel):
    description: str
    responsible: str = "Não definido"
    deadline: Optional[str] = None
    done: bool = False


class DecisionEmbedded(BaseModel):
    description: str
    context: str = ""


class SummaryEmbedded(BaseModel):
    overview: str = ""
    topics: list[str] = []
    tasks: list[TaskEmbedded] = []
    decisions: list[DecisionEmbedded] = []
    created_at: datetime = Field(default_factory=datetime.now)


class MeetingDocument(Document):
    id: str
    title: str
    started_at: datetime = Field(default_factory=datetime.now)
    audio_path: Optional[str] = None
    transcript_text: str = ""
    transcript_formatted: str = ""
    transcript_raw: str = ""
    summary: Optional[SummaryEmbedded] = None
    participants: list[str] = []
    duration_minutes: float = 0.0

    class Settings:
        name = "meetings"
        use_state_management = True

    @property
    def is_transcribed(self) -> bool:
        return bool(self.transcript_text)

    @property
    def is_summarized(self) -> bool:
        return self.summary is not None
