"""
transcript_quality_filter.py — Quality Gates anti-alucinação (Estágio 4).

Filtra segmentos do faster-whisper usando métricas do modelo para marcar
possíveis alucinações antes de persistir no banco.

Cada segmento recebe:
  - confidence: float (0-1) derivado do avg_logprob
  - reliable: bool — False se for provável alucinação
  - words: list com timestamps e probabilidades por palavra
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class QualitySegment:
    start: float
    end: float
    text: str
    speaker: str = ""
    confidence: float = 1.0
    reliable: bool = True
    words: list[dict] = field(default_factory=list)


NO_SPEECH_THRESHOLD = 0.6
LOGPROB_THRESHOLD = -1.0
COMPRESSION_RATIO_THRESHOLD = 2.4


def is_reliable(seg: Any) -> bool:
    """Métrica composta para determinar se um segmento é confiável.

    Critérios (qualquer um False -> segmento marcado como não confiável):
      1. no_speech_prob <= 0.6   (modelo acha que há fala)
      2. avg_logprob >= -1.0     (confiança mínima)
      3. compression_ratio <= 2.4 (sem repetição textual)
    """
    if hasattr(seg, "no_speech_prob") and seg.no_speech_prob > NO_SPEECH_THRESHOLD:
        return False
    if hasattr(seg, "avg_logprob") and seg.avg_logprob < LOGPROB_THRESHOLD:
        return False
    if hasattr(seg, "compression_ratio") and seg.compression_ratio > COMPRESSION_RATIO_THRESHOLD:
        return False
    return True


def apply_quality_filter(segments: list[Any]) -> list[QualitySegment]:
    """Aplica quality gates em cada segmento do faster-whisper.

    Args:
        segments: Lista de segmentos retornados pelo faster-whisper.

    Returns:
        Lista de QualitySegment com confidence, reliable e words.
    """
    result = []
    for seg in segments:
        reliable = is_reliable(seg)
        confidence = 1.0
        if hasattr(seg, "avg_logprob") and seg.avg_logprob is not None:
            confidence = round(float(np.exp(seg.avg_logprob)), 3)

        words = []
        if hasattr(seg, "words") and seg.words:
            for w in seg.words:
                words.append({
                    "word": w.word,
                    "start": w.start,
                    "end": w.end,
                    "probability": round(w.probability, 2),
                })

        result.append(QualitySegment(
            start=seg.start,
            end=seg.end,
            text=seg.text.strip(),
            confidence=confidence,
            reliable=reliable,
            words=words,
        ))

    return result
