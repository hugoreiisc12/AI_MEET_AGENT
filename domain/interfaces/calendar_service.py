# domain/interfaces/calendar_service.py
from abc import ABC, abstractmethod
from typing import Optional
from domain.entities.calendar_event import CalendarEvent


class ICalendarService(ABC):
    """Contrato para qualquer serviço de calendário."""

    @abstractmethod
    def get_current_event(self) -> Optional[CalendarEvent]:
        ...

    @abstractmethod
    def get_upcoming_events(self, limit: int = 5) -> list[CalendarEvent]:
        ...

    @abstractmethod
    def find_by_meet_url(self, meet_url: str) -> Optional[CalendarEvent]:
        ...


class CalendarServiceError(Exception):
    """Erro durante operação no calendário."""
    pass