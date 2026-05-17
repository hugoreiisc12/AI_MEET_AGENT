import os
from pathlib import Path
from openai import OpenAI

from entities.transcript import Transcript, Segment
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
    # Definindo os formatos de audio suportados para o construtor do transcritor
    SUPPORTED_FORMATS = {".": ".wav", ".mp3", ".mp4", ".m4a", ".webm", ".ogg", ".flac"}

    # Recebe o cliente OpenAI via injeção de dependência, ou cria um novo se não for fornecido
    def __init__(self, client: OpenAI | None = None) -> None:
        settings = get_settings()
        self._client = client or OpenAI(api_key=settings.openai_api_key)
        self._model = settings.whisper_model
        self._language = settings.whisper_language
        self._max_size_bytes = settings.max_audio_size_mb * 1024 * 1024

    # Interface pública (implementa ITranscriber)
    # Transcrição simples sem diarização (sem identificar falantes)
    def transcribe(self, audio_path: str) -> Transcript:
        """
        Transcrição simples — retorna texto contínuo sem identificar speakers.
        Mais rápido e barato, ideal para reuniões curtas ou testes iniciais.
        """
        self._validate_file(audio_path)

        try:
            with open(audio_path, "rb") as audio_file:
                response = self._client.audio.transcriptions.create(
                    model=self._model,
                    file=audio_file,
                    language=self._language,
                    response_format="verbose_json",  # Retorna mais metadados
                    timestamp_granularities=["segment"],
                )

            return self._build_transcript(response, audio_path, with_segments=True)

        except Exception as e:
            raise TranscriptionError(f"Whisper API falhou: {str(e)}") from e

    # Transcrição com diarização (identifica quem está falando em cada momento)
    def transcribe_with_diarization(self, audio_path: str) -> Transcript:
        """
        Transcrição com timestamps por segmento.

        Nota: O Whisper não faz diarização real (identificar speaker por voz).
        Estou usando os segmentos do Whisper como base e rotulamos "Speaker N"
        sequencialmente. Para diarização real, substituir esta implementação
        por Deepgram ou pyannote.audio sem mudar nada no domain ou use_cases.
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

            transcript = self._build_transcript(response, audio_path, with_segments=True)
            transcript = self._apply_pseudo_diarization(transcript)
            return transcript

        except Exception as e:
            raise TranscriptionError(f"Whisper API falhou: {str(e)}") from e

    # Métodos privados (detalhes de implementação)
    # Validação do arquivo de áudio e tratamento de erros específicos do arquivo
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

    # Conversão de resposta bruta da API na entity Transcript do domain
    def _build_transcript(
        self,
        response,
        audio_path: str,
        with_segments: bool,
    ) -> Transcript:
        """Converte resposta bruta da API na entity Transcript do domain."""
        full_text = response.text or ""
        segments: list[Segment] = []

        if with_segments and hasattr(response, "segments") and response.segments:
            for i, seg in enumerate(response.segments):
                segments.append(
                    Segment(
                        start=float(seg.start),
                        end=float(seg.end),
                        speaker=f"Speaker {i % 2}",  # Marcador — ele vê nota em transcribe_with_diarization
                        text=seg.text.strip(),
                    )
                )

        return Transcript(
            full_text=full_text,
            segments=segments,
            language=response.language or self._language,
            audio_path=audio_path,
        )

    # Heurística simples para simular diarização: detecta mudança de speaker por pause
    def _apply_pseudo_diarization(self, transcript: Transcript) -> Transcript:
        """
        Heurística simples: detecta mudança de speaker por pausa entre segmentos.
        Pausas > 1.5s entre segmentos → possível troca de speaker.
        Observação: Isso é apenas uma aproximação estimada.

        """
        if len(transcript.segments) < 2:
            return transcript

        current_speaker = 0
        PAUSE_THRESHOLD = 1.5  #  Time em Segundos

        for i in range(1, len(transcript.segments)):
            prev_end = transcript.segments[i - 1].end
            curr_start = transcript.segments[i].start
            pause = curr_start - prev_end

            if pause > PAUSE_THRESHOLD:
                current_speaker = 1 - current_speaker  # alterna entre 0 e 1

            transcript.segments[i].speaker = f"Speaker {current_speaker}"

        return transcript
