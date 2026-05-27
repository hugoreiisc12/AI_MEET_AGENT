# CalendarEvent enitty usado para representar eventos do Google Calendar com os dados relevantes
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class CalendarEvent:
    """Representa um evento do Google Calendar."""
    id: str
    title: str
    start: datetime
    end: datetime
    participants: list[str] = field(default_factory=list)
    meet_url: Optional[str] = None
    description: str = ""