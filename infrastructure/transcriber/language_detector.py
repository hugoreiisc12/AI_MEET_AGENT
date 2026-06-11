"""
infrastructure/transcriber/language_detector.py

Detecta o idioma do áudio e configura a transcrição corretamente.
O Whisper já detecta idioma internamente, mas este módulo expõe
essa informação de forma explícita para o usuário e permite configurar
tradução automática para o português.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from config.settings import get_settings
from infrastructure.transcriber.whisper_local_transcriber import WhisperLocalTranscriber

SUPPORTED_LANGUAGES = {
    "pt": "Português",
    "en": "English",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
    "it": "Italiano",
    "ja": "日本語",
    "zh": "中文",
    "ko": "한국어",
    "ar": "العربية",
}


@dataclass
class DetectedLanguage:
    code: str          # ex: "en", "pt", "es"
    name: str          # ex: "English", "Português"
    confidence: float  # 0.0 a 1.0
    needs_translation: bool  # True se o idioma não é o configurado como padrão


class LanguageDetector:
    """
    Detecta idioma do áudio via Whisper e determina se tradução é necessária.

    Estratégia:
      1. Chama Whisper com task="transcribe" e language=None (detecção automática)
      2. Retorna o idioma detectado com confiança
      3. Se o idioma for diferente do idioma alvo, marca needs_translation=True
    """

    def __init__(self, target_language: str = "pt") -> None:
        self._target = target_language

    def detect(self, audio_path: str) -> DetectedLanguage:
        """
        Detecta o idioma de um arquivo de áudio via Whisper local.

        Returns:
            DetectedLanguage com código, nome e se precisa de tradução
        """
        try:
            local = WhisperLocalTranscriber()
            transcript = local.transcribe(audio_path)
            code = transcript.language or self._target
            name = SUPPORTED_LANGUAGES.get(code, code.upper())
            return DetectedLanguage(
                code=code,
                name=name,
                confidence=1.0,
                needs_translation=(code != self._target),
            )
        except Exception:
            return DetectedLanguage(
                code=self._target,
                name=SUPPORTED_LANGUAGES.get(self._target, self._target),
                confidence=0.0,
                needs_translation=False,
            )