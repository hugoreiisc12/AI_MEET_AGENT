import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from domain.entities.meeting import Meeting, Summary, Task, Decision
from repositories.meeting_repository import IMeetingRepository


def _resolve_path(path: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parents[1] / path
    return p.resolve()


def _resolve_sqlite_path(database_path: str | Path) -> Path:
    path = str(database_path)
    if path.startswith("sqlite://"):
        if path.startswith("sqlite:////"):
            return Path(urlparse(path).path).resolve()
        parsed = urlparse(path)
        relative_path = parsed.path.lstrip("/")
        return _resolve_path(relative_path)
    return _resolve_path(path)


class SqliteMeetingRepository(IMeetingRepository):
    """Persistência local SQLite compartilhada entre processos."""

    def __init__(self, database_path: str | Path) -> None:
        self._db_path = _resolve_sqlite_path(database_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meetings (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                started_at TEXT NOT NULL,
                audio_path TEXT,
                transcript_text TEXT,
                transcript_formatted TEXT,
                participants_json TEXT,
                participant_info_json TEXT,
                duration_minutes REAL,
                summary_json TEXT
            )
            """
        )
        self._conn.commit()

    def save(self, meeting: Meeting) -> None:
        self._conn.execute(
            """
            INSERT INTO meetings (
                id, title, started_at, audio_path,
                transcript_text, transcript_formatted,
                participants_json, participant_info_json, duration_minutes, summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                started_at=excluded.started_at,
                audio_path=excluded.audio_path,
                transcript_text=excluded.transcript_text,
                transcript_formatted=excluded.transcript_formatted,
                participants_json=excluded.participants_json,
                participant_info_json=excluded.participant_info_json,
                duration_minutes=excluded.duration_minutes,
                summary_json=excluded.summary_json
            """,
            (
                meeting.id,
                meeting.title,
                meeting.started_at.isoformat(),
                meeting.audio_path,
                meeting.transcript_text,
                meeting.transcript_formatted,
                json.dumps(meeting.participants, ensure_ascii=False),
                json.dumps(meeting.participant_info, ensure_ascii=False),
                meeting.duration_minutes,
                json.dumps(self._serialize_summary(meeting.summary), ensure_ascii=False) if meeting.summary else None,
            ),
        )
        self._conn.commit()

    def find_by_id(self, meeting_id: str) -> Optional[Meeting]:
        cursor = self._conn.execute(
            "SELECT * FROM meetings WHERE id = ?",
            (meeting_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._deserialize(row)

    def list_all(self) -> list[Meeting]:
        cursor = self._conn.execute(
            "SELECT * FROM meetings ORDER BY started_at DESC"
        )
        return [self._deserialize(row) for row in cursor.fetchall()]

    def delete(self, meeting_id: str) -> None:
        self._conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
        self._conn.commit()

    def _serialize_summary(self, summary: Optional[Summary]) -> Optional[dict]:
        if summary is None:
            return None
        return {
            "overview": summary.overview,
            "topics": summary.topics,
            "created_at": summary.created_at.isoformat(),
            "tasks": [
                {
                    "description": t.description,
                    "responsible": t.responsible,
                    "deadline": t.deadline,
                    "done": t.done,
                }
                for t in summary.tasks
            ],
            "decisions": [
                {"description": d.description, "context": d.context}
                for d in summary.decisions
            ],
        }

    def _deserialize(self, row: sqlite3.Row) -> Meeting:
        summary = None
        if row["summary_json"]:
            summary_data = json.loads(row["summary_json"])
            summary = Summary(
                overview=summary_data.get("overview", ""),
                topics=summary_data.get("topics", []),
                created_at=datetime.fromisoformat(summary_data.get("created_at")) if summary_data.get("created_at") else datetime.now(),
                tasks=[
                    Task(
                        description=t.get("description", ""),
                        responsible=t.get("responsible", "Não definido"),
                        deadline=t.get("deadline"),
                        done=bool(t.get("done", False)),
                    )
                    for t in summary_data.get("tasks", [])
                ],
                decisions=[
                    Decision(
                        description=d.get("description", ""),
                        context=d.get("context", ""),
                    )
                    for d in summary_data.get("decisions", [])
                ],
            )
        return Meeting(
            id=row["id"],
            title=row["title"],
            started_at=datetime.fromisoformat(row["started_at"]),
            audio_path=row["audio_path"],
            transcript_text=row["transcript_text"] or "",
            transcript_formatted=row["transcript_formatted"] or "",
            participants=json.loads(row["participants_json"] or "[]"),
            participant_info=json.loads(row["participant_info_json"] or "{}"),
            duration_minutes=row["duration_minutes"] or 0.0,
            summary=summary,
        )
