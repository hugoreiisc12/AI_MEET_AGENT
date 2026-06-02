"""
infrastructure/transcriber/whisper_transcriber.py

Implementação de ITranscriber para transcrição local e via OpenAI API.

- `WhisperTranscriber` usa o OpenAI Whisper API (`openai` package)
- `WhisperLocalTranscriber` usa `openai-whisper` local

Requisitos:
    pip install openai
    pip install openai-whisper torch

Configuração no .env:
    WHISPER_TRANSCRIBER=api
    OPENAI_API_KEY=sk-...
    WHISPER_MODEL=whisper-1
    WHISPER_LANGUAGE=pt

Configuração local no .env:
    WHISPER_TRANSCRIBER=local
    WHISPER_LOCAL_MODEL=medium
    WHISPER_DEVICE=cpu
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from domain.entities.transcript import Transcript, Segment
from interface.transcriber import ITranscriber, TranscriptionError
from config.settings import get_settings


class WhisperTranscriber(ITranscriber):
    """Transcritor usando OpenAI Whisper API."""

    SUPPORTED_FORMATS = {".wav", ".mp3", ".mp4", ".m4a", ".webm", ".ogg", ".flac"}

    def __init__(
        self,
        model_name: Optional[str] = None,
        language: Optional[str] = None,
    ) -> None:
        settings = get_settings()
        self._model_name = model_name or settings.whisper_model
        self._language = language or settings.whisper_language or None
        self._api_key = settings.openai_api_key
        self._max_size_bytes = settings.max_audio_size_mb * 1024 * 1024
        self._client = None

    def transcribe(self, audio_path: str) -> Transcript:
        self._validate_file(audio_path)
        response = self._call_openai(audio_path, diarization=False)
        return self._build_transcript(response, audio_path)

    def transcribe_with_diarization(self, audio_path: str) -> Transcript:
        self._validate_file(audio_path)
        response = self._call_openai(audio_path, diarization=True)
        return self._build_transcript(response, audio_path)

    def _load_client(self):
        if self._client is not None:
            return self._client

        if not self._api_key:
            raise TranscriptionError(
                "OPENAI_API_KEY não configurada. Defina OPENAI_API_KEY no .env."
            )

        try:
            import openai
        except ImportError:
            raise TranscriptionError(
                "openai não instalado. Execute:\n"
                "  pip install openai"
            )

        self._client = openai.OpenAI(api_key=self._api_key)
        return self._client

    def _call_openai(self, audio_path: str, diarization: bool) -> dict:
        client = self._load_client()
        with open(audio_path, "rb") as f:
            kwargs = {
                "model": self._model_name,
                "file": f,
                "response_format": "verbose_json",
                "language": self._language,
            }
            if diarization:
                kwargs["timestamp_granularities"] = ["segment"]

            result = client.audio.transcriptions.create(**kwargs)

        return self._normalize_response(result)

    def _normalize_response(self, response) -> dict:
        if hasattr(response, "to_dict"):
            payload = response.to_dict()
        elif isinstance(response, dict):
            payload = response
        else:
            payload = {
                "text": getattr(response, "text", ""),
                "language": getattr(response, "language", self._language),
                "segments": getattr(response, "segments", []),
            }

        # Some response types may nest data in a `__dict__` or similar
        if not isinstance(payload, dict) and hasattr(response, "__dict__"):
            payload = dict(response.__dict__)

        return payload

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
        full_text = (getattr(result, "text", None) or result.get("text", "")).strip()
        segments: list[Segment] = []

        for seg in result.get("segments", []):
            segments.append(
                Segment(
                    start=float(seg["start"]),
                    end=float(seg["end"]),
                    speaker=seg.get("speaker", "Speaker 0"),
                    text=seg.get("text", "").strip(),
                )
            )

        return Transcript(
            full_text=full_text,
            segments=segments,
            language=result.get("language") or self._language or "pt",
            audio_path=audio_path,
        )


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

        # Precedência: parâmetro direto > settings > padrão
        self._model_name = model_name or settings.whisper_local_model
        self._language   = language   or settings.whisper_language or None
        self._device     = device     or settings.whisper_device
        self._max_size_bytes = settings.max_audio_size_mb * 1024 * 1024

        # Modelo carregado sob demanda (_lazy load)
        self._model = None

    # ── API pública ────────────────────────────────────────────────────

    def transcribe(self, audio_path: str) -> Transcript:
        """Transcrição simples sem identificação de speakers."""
        self._validate_file(audio_path)
        model = self._load_model()

        try:
            result = model.transcribe(
                audio_path,
                language=self._language,
                verbose=False,
            )
            return self._build_transcript(result, audio_path)

        except Exception as e:
            raise TranscriptionError(f"Whisper local falhou: {str(e)}") from e

    def transcribe_with_diarization(self, audio_path: str) -> Transcript:
        """
        Transcrição com pseudo-diarização baseada em pausas.
        Para diarização real, use WhisperWithDiarization (pyannote.audio).
        """
        self._validate_file(audio_path)
        model = self._load_model()

        try:
            result = model.transcribe(
                audio_path,
                language=self._language,
                verbose=False,
                word_timestamps=True,  # Whisper local suporta word-level timestamps
            )
            transcript = self._build_transcript(result, audio_path)
            transcript = self._apply_pseudo_diarization(transcript)
            return transcript

        except Exception as e:
            raise TranscriptionError(f"Whisper local falhou: {str(e)}") from e

    # ── Lazy load do modelo ────────────────────────────────────────────

    def _load_model(self):
        """Carrega o modelo na primeira chamada e reutiliza nas seguintes."""
        if self._model is not None:
            return self._model

        try:
            import whisper_local_transcriber as whisper
        except ImportError:
            raise TranscriptionError(
                "openai-whisper não instalado. Execute:\n"
                "  pip install openai-whisper\n"
                "  pip install torch  # necessário para rodar o modelo"
            )

        try:
            self._model = whisper.load_model(
                self._model_name,
                device=self._device,
            )
            return self._model
        except Exception as e:
            raise TranscriptionError(
                f"Falha ao carregar modelo '{self._model_name}': {str(e)}\n"
                f"Modelos válidos: tiny, base, small, medium, large, large-v2, large-v3"
            ) from e

    # ── Helpers ───────────────────────────────────────────────────────

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
        """
        Converte o dict retornado pelo whisper.transcribe() em Transcript.

        O Whisper local retorna:
          result["text"]     — texto completo
          result["segments"] — lista de dicts com start, end, text
          result["language"] — idioma detectado
        """
        full_text = result.get("text", "").strip()
        segments: list[Segment] = []

        for seg in result.get("segments", []):
            segments.append(
                Segment(
                    start=float(seg["start"]),
                    end=float(seg["end"]),
                    speaker="Speaker 0",  # placeholder — _apply_pseudo_diarization atribui depois
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
        """
        Heurística: pausas > 1.5s entre segmentos → possível troca de speaker.
        Alterna entre Speaker 0 e Speaker 1.
        """
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