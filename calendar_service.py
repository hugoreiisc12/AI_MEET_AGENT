from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class CalendarEvent:
    """Evento do calendário com dados da reunião."""
    id: str
    title: str
    start: datetime
    end: datetime
    participants: list[str]  # emails dos participantes
    meet_url: str = ""
    description: str = ""

    @property
    def duration_minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60


class ICalendarService(ABC):
    """Contrato para qualquer serviço de calendário."""

    @abstractmethod
    def get_current_event(self) -> Optional[CalendarEvent]:
        """Retorna o evento em andamento agora, ou None."""
        ...

    @abstractmethod
    def get_upcoming_events(self, limit: int = 5) -> list[CalendarEvent]:
        """Retorna próximos eventos com link do Meet."""
        ...

    @abstractmethod
    def find_by_meet_url(self, meet_url: str) -> Optional[CalendarEvent]:
        """Encontra evento pelo link do Google Meet."""
        ...


class CalendarServiceError(Exception):
    pass