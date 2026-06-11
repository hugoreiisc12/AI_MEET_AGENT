"""Blocos de fala de 10s com identificação do usuário real que falou."""

from dataclasses import dataclass


@dataclass
class SpeechBlock:
    """Bloco de fala de 10s associado a um usuário real da reunião."""
    user_id: str  # Email/nome real do participante (não "Speaker 0")
    text: str  # Transcrição do que foi dito
    start: float  # Início em segundos
    end: float  # Fim em segundos
    sentiment: str = "neutro"  # Tom: positivo, neutro, negativo, misto
    energy: str = "médio"  # Energia: baixo, médio, alto"
