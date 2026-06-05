# Repositório JSON para persistência local de reuniões em modo solo
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from domain.entities.meeting import Meeting, Summary, Task, Decision
from repositories.meeting_repository import IMeetingRepository
from config.settings import get_settings


# Repositório que persiste reuniões como arquivos JSON no disco
class JsonMeetingRepository(IMeetingRepository):
    """Persistência local em JSON — modo solo."""

    def __init__(self, storage_path: str | None = None) -> None:
        path = storage_path or get_settings().storage_path
        base = Path(path)
        if not base.is_absolute():
            base = Path(__file__).resolve().parents[1] / path
        self._base = base.resolve()
        self._base.mkdir(parents=True, exist_ok=True)

    # Salva reunião em arquivo JSON individual
    def save(self, meeting: Meeting) -> None:
        with open(self._base / f"{meeting.id}.json", "w", encoding="utf-8") as f:
            json.dump(self._serialize(meeting), f, ensure_ascii=False, indent=2)

    # Carrega reunião por ID, retorna None se não existe
    def find_by_id(self, meeting_id: str) -> Optional[Meeting]:
        p = self._base / f"{meeting_id}.json"
        if not p.exists():
            return None
        with open(p, encoding="utf-8") as f:
            return self._deserialize(json.load(f))

    # Retorna lista de todas as reuniões ordenadas por recentes primeiro
    def list_all(self) -> list[Meeting]:
        meetings = []
        for f in sorted(self._base.glob("*.json"), reverse=True):
            with open(f, encoding="utf-8") as fp:
                meetings.append(self._deserialize(json.load(fp)))
        return meetings

    # Deleta reunião por ID
    def delete(self, meeting_id: str) -> None:
        p = self._base / f"{meeting_id}.json"
        if p.exists():
            os.remove(p)

    # Converte Meeting entity em dicionário para serialização JSON
    def _serialize(self, m: Meeting) -> dict:
        data: dict = {
            "id": m.id,
            "title": m.title,
            "started_at": m.started_at.isoformat(),
            "audio_path": m.audio_path,
            "transcript_text": m.transcript_text,
            "transcript_formatted": m.transcript_formatted,
            "participants": m.participants,
            "participant_info": m.participant_info,
            "duration_minutes": m.duration_minutes,
            "summary": None,
        }
        if m.summary:
            s = m.summary
            data["summary"] = {
                "overview": s.overview,
                "topics": s.topics,
                "created_at": s.created_at.isoformat(),
                "tasks": [{"description": t.description, "responsible": t.responsible,
                           "deadline": t.deadline, "done": t.done} for t in s.tasks],
                "decisions": [{"description": d.description, "context": d.context}
                              for d in s.decisions],
            }
        return data

    # Converte dicionário JSON em Meeting entity
    def _deserialize(self, data: dict) -> Meeting:
        summary = None
        if data.get("summary"):
            s = data["summary"]
            summary = Summary(
                overview=s.get("overview", ""),
                topics=s.get("topics", []),
                created_at=datetime.fromisoformat(s.get("created_at", datetime.now().isoformat())),
                tasks=[Task(t["description"], t.get("responsible", "Não definido"),
                            t.get("deadline", None), t.get("done", False))
                       for t in s.get("tasks", [])],
                decisions=[Decision(d["description"], d.get("context", ""))
                           for d in s.get("decisions", [])],
            )
        return Meeting(
            id=data["id"],
            title=data["title"],
            started_at=datetime.fromisoformat(data["started_at"]),
            audio_path=data.get("audio_path"),
            transcript_text=data.get("transcript_text", ""),
            transcript_formatted=data.get("transcript_formatted", ""),
            participants=data.get("participants", []),
            participant_info=data.get("participant_info", {}),
            duration_minutes=data.get("duration_minutes", 0.0),
            summary=summary,
        )