"""Entidades e interfaces para integração com Google Calendar."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class CalendarEvent:
    """Representa um evento do Google Calendar."""
    id: str  # ID único do evento no Google Calendar
    title: str  # Título do evento
    start: datetime  # Início do evento
    end: datetime  # Fim do evento
    participants: list[str] = None  # Lista de emails dos participantes
    meet_url: Optional[str] = None  # URL do Google Meet, se houver
    description: str = ""  # Descrição do evento

    def __post_init__(self):
        if self.participants is None:
            self.participants = []


class CalendarServiceError(Exception):
    """Exceção para erros de serviço de calendário."""
    pass


class ICalendarService(ABC):
    """Interface para serviços de calendário."""

    @abstractmethod
    def get_current_event(self) -> Optional[CalendarEvent]:
        """Retorna o evento em andamento agora."""
        pass

    @abstractmethod
    def get_upcoming_events(self, limit: int = 5) -> list[CalendarEvent]:
        """Retorna próximos eventos."""
        pass

    @abstractmethod
    def find_by_meet_url(self, meet_url: str) -> Optional[CalendarEvent]:
        """Busca evento por URL do Google Meet."""
        pass
