"""
infrastructure/transcriber/whisper_transcriber.py

Transcrição local com faster-whisper + VAD (Estágios 2 e 3).

Pipeline:
  1. Preprocessa áudio com ffmpeg (highpass, lowpass, denoise, loudnorm)
  2. Aplica VAD (silero-vad) para remover silêncios
  3. Transcrição com faster-whisper (CTranslate2, beam_size=5, word_timestamps)
  4. Quality gates: no_speech_prob, avg_logprob, compression_ratio
  5. Pseudo-diarização baseada em pausas + mapping de speakers

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
from infrastructure.transcriber.audio_preprocessor import preprocess_audio, pick_device_and_compute
from infrastructure.transcriber.transcript_quality_filter import apply_quality_filter


class WhisperLocalTranscriber(ITranscriber):
    """
    Transcritor usando faster-whisper (CTranslate2) local — 4-6x mais rápido
    que openai-whisper, com suporte a VAD e word-level timestamps.

    O modelo é carregado na memória na primeira chamada e reutilizado.
    """

    SUPPORTED_FORMATS = {".wav", ".mp3", ".mp4", ".m4a", ".webm", ".ogg", ".flac"}

    GLOSSARY = (
        "reunião, Meet, OK, ok, vamos, então, gente, pessoal, "
        "feedback, projeto, sprint, task, deadline, débito técnico, "
        "POC, MVP, entregável, stakeholder, alinhamento, brainstorm"
    )

    def __init__(
        self,
        model_name: Optional[str] = None,
        language: Optional[str] = None,
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
    ) -> None:
        settings = get_settings()

        self._model_name = model_name or settings.whisper_model
        self._language   = language   or settings.whisper_language or None
        self._device     = device     or settings.whisper_device
        self._compute_type = compute_type
        self._max_size_bytes = settings.max_audio_size_mb * 1024 * 1024

        self._model = None

    def transcribe(self, audio_path: str) -> Transcript:
        self._validate_file(audio_path)
        wav_path = self._preprocess(audio_path)
        model = self._load_model()
        try:
            segments_gen, info = model.transcribe(
                str(wav_path),
                language=self._language,
                beam_size=5,
                best_of=5,
                temperature=0.0,
                vad_filter=True,
                vad_parameters=dict(
                    threshold=0.5,
                    min_speech_duration_ms=250,
                    min_silence_duration_ms=500,
                ),
                word_timestamps=True,
                condition_on_previous_text=False,
                initial_prompt=self.GLOSSARY,
                no_speech_threshold=0.6,
                compression_ratio_threshold=2.4,
                log_prob_threshold=-1.0,
            )
            raw_segments = list(segments_gen)
            quality_segments = apply_quality_filter(raw_segments)
            return self._build_transcript(quality_segments, audio_path, info)
        except Exception as e:
            raise TranscriptionError(f"Whisper falhou: {str(e)}") from e

    def transcribe_with_diarization(self, audio_path: str) -> Transcript:
        transcript = self.transcribe(audio_path)
        transcript = self._apply_pseudo_diarization(transcript)
        return transcript

    def _preprocess(self, audio_path: str) -> Path:
        path = Path(audio_path)
        if path.suffix.lower() in {".wav"} and path.stat().st_size < 50 * 1024 * 1024:
            return path
        return preprocess_audio(path)

    def _load_model(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise TranscriptionError(
                "faster-whisper não instalado. Execute:\n"
                "  pip install faster-whisper\n"
                "  pip install torch\n"
                "  pip install silero-vad"
            )
        try:
            device, compute_type = pick_device_and_compute()
            if self._compute_type:
                compute_type = self._compute_type
            self._model = WhisperModel(
                self._model_name,
                device=self._device or device,
                compute_type=compute_type,
                cpu_threads=4,
                num_workers=2,
            )
            return self._model
        except Exception as e:
            raise TranscriptionError(
                f"Falha ao carregar modelo '{self._model_name}': {str(e)}\n"
                f"Modelos válidos: tiny, base, small, medium, large-v3"
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

    def _build_transcript(
        self,
        quality_segments: list,
        audio_path: str,
        info=None,
    ) -> Transcript:
        language = info.language if info else self._language or "pt"
        full_text_parts = []
        segments: list[Segment] = []
        for qs in quality_segments:
            full_text_parts.append(qs.text)
            segments.append(
                Segment(
                    start=qs.start,
                    end=qs.end,
                    speaker="Speaker 0",
                    text=qs.text,
                    confidence=qs.confidence,
                    reliable=qs.reliable,
                    words=qs.words,
                )
            )
        full_text = " ".join(full_text_parts)
        return Transcript(
            full_text=full_text,
            segments=segments,
            language=language,
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
