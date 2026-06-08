from datetime import datetime
from typing import Optional

from beanie import Document
from pydantic import Field


class TaskDocument(Document):
    description: str
    responsible: str = "Não definido"
    deadline: Optional[str] = None
    done: bool = False

    class Settings:
        name = "tasks"


class DecisionDocument(Document):
    description: str
    context: str = ""

    class Settings:
        name = "decisions"


class SummaryDocument(Document):
    overview: str = ""
    topics: list[str] = []
    tasks: list[TaskDocument] = []
    decisions: list[DecisionDocument] = []
    created_at: datetime = Field(default_factory=datetime.now)

    class Settings:
        name = "summaries"


class SpeechBlockDocument(Document):
    user_id: str
    text: str
    start: float
    end: float
    sentiment: str = "neutro"
    energy: str = "médio"

    class Settings:
        name = "speech_blocks"


class MeetingDocument(Document):
    id: str
    title: str
    started_at: datetime
    audio_path: Optional[str] = None
    transcript_text: str = ""
    transcript_formatted: str = ""
    participants: list[str] = []
    participant_info: dict[str, str] = {}
    duration_minutes: float = 0.0
    summary: Optional[SummaryDocument] = None
    speech_blocks: list[SpeechBlockDocument] = []
    speaker_observations: list[dict] = []
    status: str = "pending"
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Settings:
        name = "meetings"
