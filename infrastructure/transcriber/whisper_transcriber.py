"""
infrastructure/transcriber/whisper_transcriber.py

Transcrição local com openai-whisper (sem API, sem custos).

Configuração no .env:
    WHISPER_MODEL=medium
    WHISPER_DEVICE=cpu
    WHISPER_LANGUAGE=pt
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from domain.entities.transcript import Transcript, Segment
from interface.transcriber import ITranscriber, TranscriptionError
from config.settings import get_settings


class WhisperLocalTranscriber(ITranscriber):
    """
    Transcritor usando openai-whisper local (sem API, sem custos por uso).

    O modelo é carregado na memória na primeira chamada e reutilizado
    nas seguintes — evita reload a cada transcrição.
    """

    SUPPORTED_FORMATS = {".wav", ".mp3", ".mp4", ".m4a", ".webm", ".ogg", ".flac"}

    def __init__(
        self,
        model_name: Optional[str] = None,
        language: Optional[str] = None,
        device: Optional[str] = None,
    ) -> None:
        settings = get_settings()

        self._model_name = model_name or settings.whisper_model
        self._language   = language   or settings.whisper_language or None
        self._device     = device     or settings.whisper_device
        self._max_size_bytes = settings.max_audio_size_mb * 1024 * 1024

        self._model = None

    def transcribe(self, audio_path: str) -> Transcript:
        self._validate_file(audio_path)
        model = self._load_model()
        try:
            result = model.transcribe(
                audio_path,
                language=self._language,
                verbose=False,
                temperature=0.0,
                compression_ratio_threshold=2.4,
                logprob_threshold=-1.0,
                no_speech_threshold=0.6,
                condition_on_previous_text=False,
            )
            return self._build_transcript(result, audio_path)
        except Exception as e:
            raise TranscriptionError(f"Whisper local falhou: {str(e)}") from e

    def transcribe_with_diarization(self, audio_path: str) -> Transcript:
        self._validate_file(audio_path)
        model = self._load_model()
        try:
            result = model.transcribe(
                audio_path,
                language=self._language,
                verbose=False,
                word_timestamps=True,
                temperature=0.0,
                compression_ratio_threshold=2.4,
                logprob_threshold=-1.0,
                no_speech_threshold=0.6,
                condition_on_previous_text=False,
            )
            transcript = self._build_transcript(result, audio_path)
            transcript = self._apply_pseudo_diarization(transcript)
            return transcript
        except Exception as e:
            raise TranscriptionError(f"Whisper local falhou: {str(e)}") from e

    def _load_model(self):
        if self._model is not None:
            return self._model
        try:
            import whisper_local_transcriber as whisper
        except ImportError:
            raise TranscriptionError(
                "openai-whisper não instalado. Execute:\n"
                "  pip install openai-whisper\n"
                "  pip install torch"
            )
        try:
            self._model = whisper.load_model(self._model_name, device=self._device)
            return self._model
        except Exception as e:
            raise TranscriptionError(
                f"Falha ao carregar modelo '{self._model_name}': {str(e)}\n"
                f"Modelos válidos: tiny, base, small, medium, large, large-v2, large-v3"
            ) from e

    def _validate_file(self, audio_path: str) -> None:
        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {audio_path}")
        if path.suffix.lower() not in self.SUPPORTED_FORMATS:
            raise TranscriptionError(
                f"Formato '{path.suffix}' não suportado. "
                f"Use: {', '.join(self.SUPPORTED_FORMATS)}"
            )
        file_size = path.stat().st_size
        if file_size > self._max_size_bytes:
            size_mb = file_size / 1024 / 1024
            raise TranscriptionError(
                f"Arquivo muito grande: {size_mb:.1f}MB. "
                f"Máximo configurado: {self._max_size_bytes // 1024 // 1024}MB."
            )

    def _build_transcript(self, result: dict, audio_path: str) -> Transcript:
        full_text = result.get("text", "").strip()
        segments: list[Segment] = []
        for seg in result.get("segments", []):
            segments.append(
                Segment(
                    start=float(seg["start"]),
                    end=float(seg["end"]),
                    speaker="Speaker 0",
                    text=seg["text"].strip(),
                )
            )
        return Transcript(
            full_text=full_text,
            segments=segments,
            language=result.get("language") or self._language or "pt",
            audio_path=audio_path,
        )

    def _apply_pseudo_diarization(self, transcript: Transcript) -> Transcript:
        if len(transcript.segments) < 2:
            return transcript
        current_speaker = 0
        PAUSE_THRESHOLD = 1.5
        for i in range(1, len(transcript.segments)):
            pause = transcript.segments[i].start - transcript.segments[i - 1].end
            if pause > PAUSE_THRESHOLD:
                current_speaker = 1 - current_speaker
            transcript.segments[i].speaker = f"Speaker {current_speaker}"
        return transcript
