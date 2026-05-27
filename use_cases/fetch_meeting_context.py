from dataclasses import dataclass
from typing import Optional
from domain.entities.calendar_event import CalendarEvent
from domain.interfaces.calendar_service import ICalendarService, CalendarServiceError

@dataclass
class FetchMeetingContextInput:
    meet_url: str = ""          # se fornecido, busca o evento específico
    use_current: bool = True    # usa o evento em andamento agora


@dataclass
class FetchMeetingContextOutput:
    event: Optional[CalendarEvent]
    success: bool
    error_message: str = ""


class FetchMeetingContextUC:
    """
    Use case: busca dados do Google Calendar para pré-preencher
    título e participantes de uma reunião antes de processá-la.

    O campo 'event' retornado pode ser usado para:
      - Pré-preencher o título no Streamlit
      - Popular a lista de participantes
      - Identificar o tipo de reunião pelo título (planning, retro, etc.)
    """

    def __init__(self, calendar_service: ICalendarService) -> None:
        self._calendar = calendar_service

    def execute(self, input_data: FetchMeetingContextInput) -> FetchMeetingContextOutput:
        try:
            if input_data.meet_url:
                event = self._calendar.find_by_meet_url(input_data.meet_url)
            elif input_data.use_current:
                event = self._calendar.get_current_event()
            else:
                event = None

            return FetchMeetingContextOutput(event=event, success=True)

        except CalendarServiceError as e:
            return FetchMeetingContextOutput(
                event=None,
                success=False,
                error_message=str(e),
            )