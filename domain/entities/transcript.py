from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class SegmentWord:
    word: str
    start: float
    end: float
    probability: float = 0.0


@dataclass
class Segment:
    start: float
    end: float
    speaker: str
    text: str
    confidence: float = 0.0
    reliable: bool = True
    words: list[SegmentWord] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start

    def __str__(self) -> str:
        minutes = int(self.start // 60)
        seconds = int(self.start % 60)
        return f"[{minutes:02d}:{seconds:02d}] {self.speaker}: {self.text}"


@dataclass
class Transcript:
    full_text: str
    segments: list[Segment] = field(default_factory=list)
    language: str = "pt"
    created_at: datetime = field(default_factory=datetime.now)
    audio_path: Optional[str] = None
    text_raw: str = ""

    @property
    def has_diarization(self) -> bool:
        return len(self.segments) > 0

    @property
    def formatted(self) -> str:
        if self.has_diarization:
            return "\n".join(str(seg) for seg in self.segments)
        return self.full_text

    @property
    def duration_minutes(self) -> float:
        if self.segments:
            return self.segments[-1].end / 60
        return 0.0

    @property
    def speakers(self) -> list[str]:
        return list(dict.fromkeys(seg.speaker for seg in self.segments))
