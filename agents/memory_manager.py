from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from domain.entities.meeting import Meeting
from repositories.meeting_repository import IMeetingRepository


MEMORY_DEFAULTS = {
    "short_term_max": 5,
    "medium_term_threshold": 3,
    "long_term_threshold": 10,
}


class ShortTermMemory:
    """Memória de curto prazo — últimos N meetings em memória."""

    def __init__(self, max_size: int = 5) -> None:
        self._max_size = max_size
        self._meetings: list[Meeting] = []

    def add(self, meeting: Meeting) -> None:
        self._meetings.append(meeting)
        if len(self._meetings) > self._max_size:
            self._meetings.pop(0)

    def get_all(self) -> list[Meeting]:
        return list(reversed(self._meetings))

    def get_last(self, n: int = 1) -> list[Meeting]:
        return list(reversed(self._meetings[-n:]))

    @property
    def count(self) -> int:
        return len(self._meetings)

    @property
    def is_full(self) -> bool:
        return len(self._meetings) >= self._max_size


class MediumTermMemory:
    """Memória de médio prazo — a cada N inputs, salva sumário no banco."""

    def __init__(
        self,
        repository: IMeetingRepository,
        threshold: int = 3,
    ) -> None:
        self._repository = repository
        self._threshold = threshold
        self._last_snapshot_input = 0

    def should_snapshot(self, input_count: int) -> bool:
        return (input_count - self._last_snapshot_input) >= self._threshold

    def take_snapshot(self, input_count: int, recent_meetings: list[Meeting]) -> Optional[str]:
        if not recent_meetings:
            return None
        snapshot = {
            "type": "medium_term",
            "input_count": input_count,
            "timestamp": datetime.now().isoformat(),
            "meetings_count": len(recent_meetings),
            "titles": [m.title for m in recent_meetings],
            "participants": list({
                p for m in recent_meetings for p in (m.participants or [])
            }),
            "total_duration_min": sum(
                m.duration_minutes or 0 for m in recent_meetings
            ),
        }
        self._last_snapshot_input = input_count
        return self._persist_snapshot(snapshot)

    def _persist_snapshot(self, snapshot: dict) -> str:
        snapshot_id = f"med_{int(time.time())}"
        path = Path("data/memory") / f"{snapshot_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return snapshot_id


class LongTermMemory:
    """Memória de longo prazo — a cada N inputs, salva tendências no banco."""

    def __init__(
        self,
        repository: IMeetingRepository,
        threshold: int = 10,
    ) -> None:
        self._repository = repository
        self._threshold = threshold
        self._last_snapshot_input = 0

    def should_snapshot(self, input_count: int) -> bool:
        return (input_count - self._last_snapshot_input) >= self._threshold

    def take_snapshot(self, input_count: int, all_meetings: list[Meeting]) -> Optional[str]:
        if not all_meetings:
            return None
        all_participants = list({
            p for m in all_meetings for p in (m.participants or [])
        })
        snapshot = {
            "type": "long_term",
            "input_count": input_count,
            "timestamp": datetime.now().isoformat(),
            "total_meetings": len(all_meetings),
            "unique_participants": all_participants,
            "total_duration_min": sum(
                m.duration_minutes or 0 for m in all_meetings
            ),
        }
        self._last_snapshot_input = input_count
        return self._persist_snapshot(snapshot)

    def _persist_snapshot(self, snapshot: dict) -> str:
        snapshot_id = f"long_{int(time.time())}"
        path = Path("data/memory") / f"{snapshot_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return snapshot_id


class MemoryManager:
    """Gerencia os três níveis de memória: curta, média e longa."""

    def __init__(
        self,
        repository: IMeetingRepository,
        short_term_max: int = 5,
        medium_term_threshold: int = 3,
        long_term_threshold: int = 10,
    ) -> None:
        self.short = ShortTermMemory(max_size=short_term_max)
        self.medium = MediumTermMemory(
            repository=repository, threshold=medium_term_threshold,
        )
        self.long = LongTermMemory(
            repository=repository, threshold=long_term_threshold,
        )
        self._input_count = 0

    def on_input(self, meeting: Meeting) -> None:
        """Chamado a cada novo meeting inserido no banco."""
        self._input_count += 1
        self.short.add(meeting)

        if self.medium.should_snapshot(self._input_count):
            snapshot_id = self.medium.take_snapshot(
                self._input_count, self.short.get_all(),
            )
            if snapshot_id:
                print(f"🧠 Memória média salva: {snapshot_id}")

        if self.long.should_snapshot(self._input_count):
            from presentation.container import get_container
            container = get_container()
            all_meetings = container.repository.list_all()
            snapshot_id = self.long.take_snapshot(
                self._input_count, all_meetings,
            )
            if snapshot_id:
                print(f"🧠 Memória longa salva: {snapshot_id}")

    @property
    def input_count(self) -> int:
        return self._input_count

    def get_context(self) -> dict:
        """Retorna contexto completo das memórias para o chat."""
        return {
            "input_count": self._input_count,
            "short_term": {
                "count": self.short.count,
                "meetings": [
                    {"id": m.id, "title": m.title}
                    for m in self.short.get_all()
                ],
            },
            "medium_term": {
                "threshold": self.medium._threshold,
                "last_snapshot": self.medium._last_snapshot_input,
            },
            "long_term": {
                "threshold": self.long._threshold,
                "last_snapshot": self.long._last_snapshot_input,
            },
        }
