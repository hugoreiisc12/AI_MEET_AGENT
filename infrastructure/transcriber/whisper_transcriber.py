"""
infrastructure/transcriber/whisper_transcriber.py

Implementação de ITranscriber para transcrição via OpenAI API e local (faster-whisper).

- `WhisperTranscriber` usa o OpenAI Whisper API
- `WhisperLocalTranscriber` usa faster-whisper (CTranslate2) com VAD + quality gates
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

from domain.entities.transcript import Transcript, Segment
from interface.transcriber import ITranscriber, TranscriptionError
from config.settings import get_settings
from infrastructure.transcriber.audio_preprocessor import preprocess_audio
from infrastructure.transcriber.transcript_quality_filter import filter_segments


def pick_device_and_compute():
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


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
    Transcritor usando faster-whisper (CTranslate2) com:
      - Silero VAD embutido (elimina alucinação em silêncio)
      - Segmentação inteligente (sem cortes fixos de 30s)
      - Quality gates (confidence, reliable, word timestamps)
      - Pré-processamento de áudio (ffmpeg denoise + loudnorm)
    """

    SUPPORTED_FORMATS = {".wav", ".mp3", ".mp4", ".m4a", ".webm", ".ogg", ".flac"}

    def __init__(
        self,
        model_name: Optional[str] = None,
        language: Optional[str] = None,
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
    ) -> None:
        settings = get_settings()

        self._model_name = model_name or settings.whisper_local_model
        self._language = language or settings.whisper_language or None
        self._max_size_bytes = settings.max_audio_size_mb * 1024 * 1024

        if device and compute_type:
            self._device = device
            self._compute_type = compute_type
        else:
            self._device, self._compute_type = pick_device_and_compute()

        self._model = None

    def transcribe(self, audio_path: str) -> Transcript:
        self._validate_file(audio_path)
        return self._transcribe_with_pipeline(audio_path, diarization=False)

    def transcribe_with_diarization(self, audio_path: str) -> Transcript:
        self._validate_file(audio_path)
        return self._transcribe_with_pipeline(audio_path, diarization=True)

    def _transcribe_with_pipeline(self, audio_path: str, diarization: bool) -> Transcript:
        audio_path_obj = Path(audio_path)

        try:
            wav_path = preprocess_audio(audio_path_obj)
        except Exception as e:
            raise TranscriptionError(f"Pré-processamento de áudio falhou: {e}") from e

        model = self._load_model()

        try:
            segments, info = model.transcribe(
                str(wav_path),
                language=self._language or "pt",
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                condition_on_previous_text=False,
                word_timestamps=True,
                initial_prompt=self._build_initial_prompt(),
            )

            raw_segments = []
            for seg in segments:
                words_list = []
                for w in (seg.words or []):
                    words_list.append({
                        "word": w.word,
                        "start": w.start,
                        "end": w.end,
                        "probability": w.probability,
                    })
                raw_segments.append({
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text.strip(),
                    "speaker": "Speaker 0",
                    "avg_logprob": seg.avg_logprob,
                    "no_speech_prob": seg.no_speech_prob,
                    "compression_ratio": seg.compression_ratio,
                    "words": words_list,
                })

            clean_segments = filter_segments(raw_segments)

            if diarization:
                clean_segments = self._apply_pseudo_diarization(clean_segments)

            full_text = " ".join(s["text"] for s in clean_segments if s["reliable"])

            segments_entities = [
                Segment(
                    start=s["start"],
                    end=s["end"],
                    speaker=s["speaker"],
                    text=s["text"],
                )
                for s in clean_segments
            ]

            transcript = Transcript(
                full_text=full_text,
                segments=segments_entities,
                language=info.language or self._language or "pt",
                audio_path=wav_path,
            )

            if wav_path.suffix == ".clean.wav":
                try:
                    wav_path.unlink()
                except Exception:
                    pass

            return transcript

        except Exception as e:
            raise TranscriptionError(f"faster-whisper falhou: {str(e)}") from e

    def _load_model(self):
        if self._model is not None:
            return self._model

        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise TranscriptionError(
                "faster-whisper não instalado. Execute:\n"
                "  pip install faster-whisper\n"
                "  pip install imageio-ffmpeg"
            )

        try:
            self._model = WhisperModel(
                self._model_name,
                device=self._device,
                compute_type=self._compute_type,
            )
            return self._model
        except Exception as e:
            raise TranscriptionError(
                f"Falha ao carregar modelo '{self._model_name}': {str(e)}\n"
                f"Modelos: tiny, base, small, medium, large-v3"
            ) from e

    def _build_initial_prompt(self) -> str:
        return (
            "Reunião de trabalho em português do Brasil. "
            "Termos frequentes: Power BI, DAX, dashboard, faturamento, "
            "inadimplência, Streamlit, FastAPI, deploy, sprint, backlog."
        )

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

    def _apply_pseudo_diarization(self, segments: list[dict]) -> list[dict]:
        if len(segments) < 2:
            return segments

        current_speaker = 0
        PAUSE_THRESHOLD = 1.5

        for i in range(1, len(segments)):
            pause = segments[i]["start"] - segments[i - 1]["end"]
            if pause > PAUSE_THRESHOLD:
                current_speaker = 1 - current_speaker
            segments[i]["speaker"] = f"Speaker {current_speaker}"

        return segments
