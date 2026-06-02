"""Alias para o transcritor local de Whisper.

O container espera importar `WhisperLocalTranscriber` de
`infrastructure.transcriber.whisper_local_transcriber`.

Aqui apenas encaminhamos para a implementação existente em
`infrastructure/transcriber/whisper_transcriber.py`.
"""

from .whisper_transcriber import WhisperLocalTranscriber

__all__ = ["WhisperLocalTranscriber"]
