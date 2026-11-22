"""Conversão Meeting <-> dict, compartilhada pelos repositórios JSON e Mongo."""
from dataclasses import asdict
from datetime import datetime

from domain.entities.meeting import Decision, Meeting, MeetingStatus, Summary, Task


def meeting_to_dict(meeting: Meeting) -> dict:
    data = asdict(meeting)
    data["status"] = meeting.status.value
    return data


def _to_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value) if value else datetime.now()


def _status(data: dict, has_summary: bool) -> MeetingStatus:
    try:
        return MeetingStatus(data["status"])
    except (KeyError, ValueError):
        # Documento anterior ao campo status: deriva do conteúdo.
        return MeetingStatus.DONE if has_summary else MeetingStatus.PENDING


def meeting_from_dict(data: dict) -> Meeting:
    summary = None
    if s := data.get("summary"):
        summary = Summary(
            overview=s.get("overview", ""),
            topics=s.get("topics") or [],
            tasks=[
                Task(t["description"], t.get("responsible", "Não definido"),
                     t.get("deadline"), t.get("done", False))
                for t in s.get("tasks") or []
            ],
            decisions=[
                Decision(d["description"], d.get("context", ""), d.get("status", ""))
                for d in s.get("decisions") or []
            ],
            created_at=_to_datetime(s.get("created_at")),
            contributions=s.get("contributions") or [],
            topic_decisions=s.get("topic_decisions") or [],
            open_questions=s.get("open_questions") or [],
        )
    return Meeting(
        id=data.get("id") or data["_id"],
        title=data.get("title", ""),
        owner_id=data.get("owner_id") or "",
        platform=data.get("platform") or "",
        meeting_url=data.get("meeting_url") or "",
        source_id=data.get("source_id") or "",
        started_at=_to_datetime(data.get("started_at")),
        audio_path=data.get("audio_path"),
        transcript_text=data.get("transcript_text") or "",
        transcript_formatted=data.get("transcript_formatted") or "",
        transcript_raw=data.get("transcript_raw") or "",
        summary=summary,
        participants=data.get("participants") or [],
        duration_minutes=data.get("duration_minutes") or 0.0,
        status=_status(data, summary is not None),
        status_at=_to_datetime(data["status_at"]) if data.get("status_at") else None,
        error=data.get("error") or "",
        chat_history=data.get("chat_history") or [],
        metrics=data.get("metrics") or {},
        queue=data.get("queue") or "",
        queue_priority=data.get("queue_priority") or 0,
        queued_at=_to_datetime(data["queued_at"]) if data.get("queued_at") else None,
    )
