"""Entidades para análise de sentimento e engajamento em reuniões."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SpeakerSentiment:
    """Análise de sentimento de um speaker específico."""
    speaker: str  # Nome ou ID do speaker
    overall_tone: str = "neutro"  # Tom geral (positivo, neutro, negativo, etc.)
    energy_level: str = "médio"  # Nível de energia (baixo, médio, alto)
    engagement_score: float = 0.5  # Score de engajamento (0-1)
    talk_time_ratio: float = 0.0  # Proporção de tempo falando
    key_emotions: list[str] = field(default_factory=list)  # Emoções detectadas
    highlights: list[str] = field(default_factory=list)  # Momentos mais positivos


@dataclass
class SentimentResult:
    """Resultado completo da análise de sentimento de uma reunião."""
    overall_tone: str = "neutro"  # Tom geral da reunião
    energy_level: str = "médio"  # Nível de energia geral
    meeting_mood: str = ""  # Descrição do clima/humor geral
    collaboration_score: float = 0.5  # Score de colaboração (0-1)
    tension_moments: list[str] = field(default_factory=list)  # Momentos de tensão
    positive_moments: list[str] = field(default_factory=list)  # Momentos positivos
    speakers: list[SpeakerSentiment] = field(default_factory=list)  # Análise por speaker
    created_at: datetime = field(default_factory=datetime.now)  # Quando foi criado
