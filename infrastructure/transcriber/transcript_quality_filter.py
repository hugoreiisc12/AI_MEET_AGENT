"""
transcript_quality_filter.py — Filtro anti-alucinação (Estágio 4).

Métrica por segmento do faster-whisper:
  - no_speech_prob > 0.6 → modelo acha que não há fala → unreliable
  - avg_logprob < -1.0   → confiança muito baixa → unreliable
  - compression_ratio > 2.4 → texto repetitivo (loop de alucinação) → unreliable
"""


def is_reliable(seg: dict) -> bool:
    if seg.get("no_speech_prob", 0) > 0.6:
        return False
    if seg.get("avg_logprob", 0) < -1.0:
        return False
    if seg.get("compression_ratio", 0) > 2.4:
        return False
    return True


def filter_segments(segments: list[dict]) -> list[dict]:
    result = []
    for seg in segments:
        result.append({
            "start": seg.get("start", 0),
            "end": seg.get("end", 0),
            "text": seg.get("text", "").strip(),
            "speaker": seg.get("speaker", "Speaker 0"),
            "confidence": round(float(seg.get("avg_logprob", -2)), 3),
            "reliable": is_reliable(seg),
            "no_speech_prob": round(float(seg.get("no_speech_prob", 0)), 4),
            "words": [
                {
                    "word": w.get("word", ""),
                    "start": w.get("start", 0),
                    "end": w.get("end", 0),
                    "probability": round(float(w.get("probability", 0)), 2),
                }
                for w in (seg.get("words") or [])
            ],
        })
    return result
