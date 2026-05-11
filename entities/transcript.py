# Entidades do dominio relacionadas a transcrição em reuniões, como Segmentos e Transcrição completa
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# Defiinindo uma classe de segmento, que representa um trecho da transcrição
@dataclass
class Segment:
    """Um trecho da transcrição com speaker e tempo."""
    start: float          # segundos
    end: float            # segundos
    speaker: str          # ex: "Speaker 0"
    text: str

# Propriedade calculada para duração do segmento, e método de formatação para exibição légivel
    @property
    def duration(self) -> float:
        return self.end - self.start

# Formatação do segmento para exiber o timestamp, speaker e texto de forma légivel
    def __str__(self) -> str:
        minutes = int(self.start // 60)
        seconds = int(self.start % 60)
        return f"[{minutes:02d}:{seconds:02d}] {self.speaker}: {self.text}"

# Definindo a classe de transcrição completa de uma reunião
@dataclass
class Transcript:
    """Transcrição completa de uma reunião."""
    full_text: str
    segments: list[Segment] = field(default_factory=list)
    language: str = "pt"
    created_at: datetime = field(default_factory=datetime.now)
    audio_path: Optional[str] = None

# Propriedades calculadas para facilitar o acesso a informações derivadas da transcrição
    @property
    def has_diarization(self) -> bool:
        """Verifica se a transcrição tem identificação de speakers."""
        return len(self.segments) > 0

# Formatação do transcript completo, exibindo segmentos formatados se houver diarização
    @property
    def formatted(self) -> str:
        """Texto formatado com timestamps e speakers."""
        if self.has_diarization:
            return "\n".join(str(seg) for seg in self.segments)
        return self.full_text

# Propriedade para estimar a duração total da reunião com base nos segmentos do timestamp do ultimo segmento
    @property
    def duration_minutes(self) -> float:
        """Duração total estimada em minutos."""
        if self.segments:
            return self.segments[-1].end / 60
        return 0.0

# Identifica os speakers únicos presentes na transcrição, útil para análises posteriores
    @property
    def speakers(self) -> list[str]:
        """Lista de speakers únicos identificados."""
        return list(dict.fromkeys(seg.speaker for seg in self.segments))
