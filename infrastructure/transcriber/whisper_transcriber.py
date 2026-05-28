import os
from pathlib import Path
from openai import OpenAI

from domain.entities.transcript import Transcript, Segment
from interface.transcriber import ITranscriber, TranscriptionError
from config.settings import get_settings


class WhisperTranscriber(ITranscriber):
    """
    Implementação de ITranscriber usando a API Whisper da OpenAI.

    Responsabilidades:
      - Validar arquivo antes de enviar
      - Chamar a API com os parâmetros corretos
      - Converter resposta da API nas entities do domain
      - Nunca deixar exceções da OpenAI vazarem para fora (encapsula em TranscriptionError)
    """
    SUPPORTED_FORMATS = {".wav", ".mp3", ".mp4", ".m4a", ".webm", ".ogg", ".flac"}

    def __init__(self, client: OpenAI | None = None) -> None:
        settings = get_settings()
        self._client = client or OpenAI(api_key=settings.openai_api_key)
        self._model = settings.whisper_model
        self._language = settings.whisper_language
        self._max_size_bytes = settings.max_audio_size_mb * 1024 * 1024

    def transcribe(self, audio_path: str) -> Transcript:
        """
        Transcrição simples — retorna texto contínuo sem identificar speakers.
        """
        self._validate_file(audio_path)

        try:
            with open(audio_path, "rb") as audio_file:
                response = self._client.audio.transcriptions.create(
                    model=self._model,
                    file=audio_file,
                    language=self._language,
                    response_format="verbose_json",
                    timestamp_granularities=["segment"],
                )

            return self._build_transcript(response, audio_path, with_segments=True)

        except Exception as e:
            raise TranscriptionError(f"Whisper API falhou: {str(e)}") from e

    def transcribe_with_diarization(self, audio_path: str) -> Transcript:
        """
        Transcrição com pseudo-diarização baseada em pausas entre segmentos.

        Nota: Whisper não faz diarização real. Speakers são rotulados por heurística
        de pausa. Para diarização real, use WhisperWithDiarization (pyannote.audio).
        """
        self._validate_file(audio_path)

        try:
            with open(audio_path, "rb") as audio_file:
                response = self._client.audio.transcriptions.create(
                    model=self._model,
                    file=audio_file,
                    language=self._language,
                    response_format="verbose_json",
                    timestamp_granularities=["segment", "word"],
                )

            # FIX: _build_transcript cria todos os segmentos com speaker="Speaker 0"
            # (placeholder neutro). _apply_pseudo_diarization sobrescreve depois.
            transcript = self._build_transcript(response, audio_path, with_segments=True)
            transcript = self._apply_pseudo_diarization(transcript)
            return transcript

        except Exception as e:
            raise TranscriptionError(f"Whisper API falhou: {str(e)}") from e

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
                f"Máximo permitido pela API: {self._max_size_bytes // 1024 // 1024}MB. "
                "Considere dividir o áudio em partes."
            )

    def _build_transcript(
        self,
        response,
        audio_path: str,
        with_segments: bool,
    ) -> Transcript:
        """Converte resposta bruta da API na entity Transcript do domain.

        Todos os segmentos recebem speaker="Speaker 0" como placeholder.
        Quem chama transcribe_with_diarization() deve chamar
        _apply_pseudo_diarization() em seguida para atribuir speakers reais.
        """
        full_text = response.text or ""
        segments: list[Segment] = []

        if with_segments and hasattr(response, "segments") and response.segments:
            for seg in response.segments:
                segments.append(
                    Segment(
                        start=float(seg.start),
                        end=float(seg.end),
                        # FIX: era `f"Speaker {i % 2}"` — alternava 0/1 por índice,
                        # conflitando com _apply_pseudo_diarization que faz o mesmo
                        # por pausa. Agora todos começam como Speaker 0 (placeholder).
                        speaker="Speaker 0",
                        text=seg.text.strip(),
                    )
                )

        return Transcript(
            full_text=full_text,
            segments=segments,
            language=response.language or self._language,
            audio_path=audio_path,
        )

    def _apply_pseudo_diarization(self, transcript: Transcript) -> Transcript:
        """
        Heurística: detecta troca de speaker por pausa entre segmentos.
        Pausas > 1.5s → possível novo speaker.
        Limitação conhecida: alterna apenas entre Speaker 0 e Speaker 1.
        """
        if len(transcript.segments) < 2:
            return transcript

        current_speaker = 0
        PAUSE_THRESHOLD = 1.5  # segundos

        # Primeiro segmento já está correto (Speaker 0 do _build_transcript)
        for i in range(1, len(transcript.segments)):
            prev_end = transcript.segments[i - 1].end
            curr_start = transcript.segments[i].start
            pause = curr_start - prev_end

            if pause > PAUSE_THRESHOLD:
                current_speaker = 1 - current_speaker  # alterna 0 ↔ 1

            transcript.segments[i].speaker = f"Speaker {current_speaker}"

        return transcript