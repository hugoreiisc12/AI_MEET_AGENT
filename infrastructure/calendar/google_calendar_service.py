"""
infrastructure/calendar/google_calendar_service.py

Integração com Google Calendar API v3.
Pré-carrega título e participantes antes da reunião começar.

Requer:
    pip install google-auth google-auth-oauthlib google-api-python-client

Configuração OAuth:
    1. Console Cloud → APIs & Serviços → Credenciais
    2. Criar credencial OAuth 2.0 para Desktop
    3. Baixar credentials.json e colocar na raiz do projeto
    4. Na primeira execução, abre o browser para autorizar
    5. Salva token.json automaticamente para reusos futuros

Variáveis de ambiente:
    GOOGLE_CREDENTIALS_PATH=credentials.json  (padrão)
    GOOGLE_TOKEN_PATH=token.json              (padrão)
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse
from typing import Optional

from domain.entities.calendar_event import ICalendarService, CalendarEvent, CalendarServiceError

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


class GoogleCalendarService(ICalendarService):
    """
    Implementação de ICalendarService usando Google Calendar API v3.
    Autentica via OAuth 2.0 com token persistido em arquivo local.
    """

    def __init__(
        self,
        credentials_path: str = "credentials.json",
        token_path: str = "token.json",
    ) -> None:
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._service = None  # lazy

    def get_current_event(self) -> Optional[CalendarEvent]:
        """Retorna reunião em andamento agora (±5 min de tolerância)."""
        now = datetime.now(timezone.utc)
        window_start = (now - timedelta(minutes=5)).isoformat()
        window_end   = (now + timedelta(minutes=5)).isoformat()

        events = self._fetch_events(
            time_min=window_start,
            time_max=window_end,
            max_results=5,
        )

        meet_events = [e for e in events if e.meet_url]
        return meet_events[0] if meet_events else None

    def get_upcoming_events(self, limit: int = 5) -> list[CalendarEvent]:
        """Retorna próximos eventos com link do Meet."""
        now = datetime.now(timezone.utc).isoformat()
        events = self._fetch_events(
            time_min=now,
            max_results=limit * 2,
        )
        return [e for e in events if e.meet_url][:limit]

    def find_by_meet_url(self, meet_url: str) -> Optional[CalendarEvent]:
        """Encontra evento pelo código da sala do Meet."""
        # Extrai o código da URL de forma segura, ignorando query strings
        parsed = urlparse(meet_url)
        code = parsed.path.rstrip("/").split("/")[-1]

        now = datetime.now(timezone.utc)
        window_start = (now - timedelta(hours=2)).isoformat()
        window_end   = (now + timedelta(hours=24)).isoformat()

        events = self._fetch_events(
            time_min=window_start,
            time_max=window_end,
            max_results=20,
        )

        for event in events:
            if event.meet_url and code in event.meet_url:
                return event
        return None

    # ── Privados ──────────────────────────────────────────────────────────

    def _get_service(self):
        """Carrega credenciais e retorna o serviço da API (lazy)."""
        if self._service:
            return self._service

        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
        except ImportError:
            raise CalendarServiceError(
                "Bibliotecas do Google não instaladas.\n"
                "Execute: pip install google-auth google-auth-oauthlib google-api-python-client"
            )

        creds = None
        token_path = Path(self._token_path)

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not Path(self._credentials_path).exists():
                    raise CalendarServiceError(
                        f"credentials.json não encontrado em '{self._credentials_path}'.\n"
                        "Baixe de: console.cloud.google.com → APIs → Credenciais"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    self._credentials_path, SCOPES
                )
                creds = flow.run_local_server(port=0)

            with open(token_path, "w") as f:
                f.write(creds.to_json())

        self._service = build("calendar", "v3", credentials=creds)
        return self._service

    def _fetch_events(
        self,
        time_min: str,
        time_max: str | None = None,
        max_results: int = 10,
    ) -> list[CalendarEvent]:
        """Busca eventos no calendário primário."""
        try:
            service = self._get_service()
            kwargs = dict(
                calendarId="primary",
                timeMin=time_min,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            if time_max:
                kwargs["timeMax"] = time_max

            result = service.events().list(**kwargs).execute()
            items = result.get("items", [])
            return [self._parse_event(item) for item in items]

        except CalendarServiceError:
            raise
        except Exception as e:
            if "quota" in str(e).lower() or "403" in str(e):
                raise CalendarServiceError(
                    "Quota da Google Calendar API excedida. Tente novamente em alguns minutos."
                ) from e
            raise CalendarServiceError(f"Erro ao buscar eventos: {str(e)}") from e

    def _parse_event(self, item: dict) -> CalendarEvent:
        """Converte resposta da API em CalendarEvent."""
        start_raw = item.get("start", {})
        end_raw   = item.get("end", {})

        start = self._parse_dt(start_raw.get("dateTime") or start_raw.get("date", ""))
        end   = self._parse_dt(end_raw.get("dateTime") or end_raw.get("date", ""))

        attendees = [
            a.get("email", "")
            for a in item.get("attendees", [])
            if not a.get("self", False)
        ]

        meet_url = ""
        entry_points = item.get("conferenceData", {}).get("entryPoints", [])
        for ep in entry_points:
            if ep.get("entryPointType") == "video":
                meet_url = ep.get("uri", "")
                break

        return CalendarEvent(
            id=item.get("id", ""),
            title=item.get("summary", "Reunião sem título"),
            start=start,
            end=end,
            participants=attendees,
            meet_url=meet_url,
            description=item.get("description", ""),
        )

    @staticmethod
    def _parse_dt(value: str) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        try:
            if "T" in value:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            d = datetime.strptime(value, "%Y-%m-%d")
            return d.replace(tzinfo=timezone.utc)
        except ValueError:
            return datetime.now(timezone.utc)