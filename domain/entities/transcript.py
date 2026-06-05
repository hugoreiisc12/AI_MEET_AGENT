# Entidades do domínio relacionadas a transcrição em reuniões
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# Representa um trecho de transcrição com speaker, tempo e texto
@dataclass
class Segment:
    """Um segmento da transcrição com speaker e tempo."""
    start: float  # Tempo inicial em segundos
    end: float  # Tempo final em segundos
    speaker: str  # Nome do speaker (ex: "Speaker 0")
    text: str  # Texto do segmento

    # Calcula duração do segmento em segundos
    @property
    def duration(self) -> float:
        return self.end - self.start

    # Formata segmento como [HH:MM] Speaker: texto para exibição
    def __str__(self) -> str:
        minutes = int(self.start // 60)
        seconds = int(self.start % 60)
        return f"[{minutes:02d}:{seconds:02d}] {self.speaker}: {self.text}"


# Representa a transcrição completa de uma reunião
@dataclass
class Transcript:
    """Transcrição completa de uma reunião com segmentos e metadados."""
    full_text: str  # Texto completo sem formatação
    segments: list[Segment] = field(default_factory=list)  # Segmentos com speaker e tempo
    language: str = "pt"  # Idioma da transcrição
    created_at: datetime = field(default_factory=datetime.now)  # Quando foi criada
    audio_path: Optional[str] = None  # Caminho do arquivo de áudio original
    speaker_aliases: dict[str, str] = field(default_factory=dict)  # Mapeamento speaker -> email/nome real

    # Verifica se tem diarização (identificação de speakers)
    @property
    def has_diarization(self) -> bool:
        return len(self.segments) > 0

    # Retorna transcrição formatada com timestamps ou apenas o texto
    @property
    def formatted(self) -> str:
        if self.has_diarization:
            return "\n".join(
                f"[{int(seg.start // 60):02d}:{int(seg.start % 60):02d}] {self.get_speaker_label(seg.speaker)}: {seg.text}"
                for seg in self.segments
            )
        return self.full_text

    def get_speaker_label(self, speaker_id: str) -> str:
        """Retorna o nome real do speaker, se houver mapeamento."""
        return self.speaker_aliases.get(speaker_id, speaker_id)

    def apply_speaker_mapping(self, mapping: dict[str, str]) -> None:
        """Substitui os ids de speaker pelos nomes ou emails fornecidos."""
        self.speaker_aliases.update(mapping)
        for segment in self.segments:
            if segment.speaker in mapping:
                segment.speaker = mapping[segment.speaker]

    # Calcula duração total da reunião em minutos
    @property
    def duration_minutes(self) -> float:
        if self.segments:
            return self.segments[-1].end / 60
        return 0.0

    # Retorna lista de speakers únicos identificados
    @property
    def speakers(self) -> list[str]:
        return list(dict.fromkeys(seg.speaker for seg in self.segments))
