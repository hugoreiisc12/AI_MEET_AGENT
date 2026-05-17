"""
infrastructure/transcriber/pyannote_diarizer.py

Diarização real usando pyannote.audio.
Identifica quem falou em cada trecho do áudio com base em características
acústicas da voz — sem heurística de pausa.

Requer:
    pip install pyannote.audio
    Token do HuggingFace com acesso ao modelo pyannote/speaker-diarization-3.1
    (aceitar termos em hf.co/pyannote/speaker-diarization-3.1)

Variáveis de ambiente:
    HUGGINGFACE_TOKEN=hf_...
    USE_REAL_DIARIZATION=true
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from interface.transcriber import TranscriptionError


@dataclass
class DiarizationSegment:
    """Segmento de fala identificado pelo pyannote."""

    start: float
    end: float
    speaker: str  # ex: "SPEAKER_00", "SPEAKER_01"


class PyannoteDiarizer:
    """
    Wrapper do pyannote.audio para diarização de áudio.

    Responsabilidade única: receber um arquivo de áudio e devolver
    uma lista de DiarizationSegment dizendo quem falou quando.

    O alinhamento com o texto do Whisper é feito em WhisperWithDiarization.
    """

    MODEL_ID = "pyannote/speaker-diarization-3.1"

    def __init__(
        self,
        hf_token: str,
        num_speakers: Optional[int] = None,
        min_speakers: int = 1,
        max_speakers: int = 10,
        device: str = "cpu",
    ) -> None:
        """
        Args:
            hf_token:     Token HuggingFace com acesso ao modelo pyannote
            num_speakers: Número exato de speakers (None = detecta automaticamente)
            min_speakers: Mínimo de speakers esperados
            max_speakers: Máximo de speakers esperados
            device:       "cpu" ou "cuda" (GPU acelera significativamente)
        """
        self._hf_token  = hf_token
        self._num       = num_speakers
        self._min       = min_speakers
        self._max       = max_speakers
        self._device    = device
        self._pipeline  = None  # carregado lazy na primeira chamada

    # ------------------------------------------------------------------
    # Interface pública
    # ------------------------------------------------------------------

    def diarize(self, audio_path: str) -> list[DiarizationSegment]:
        """
        Roda diarização no arquivo e retorna lista de segmentos com speaker.

        Args:
            audio_path: Caminho para .wav (mono, 16kHz preferível)

        Returns:
            Lista ordenada por tempo com speaker identificado

        Raises:
            TranscriptionError: se o modelo falhar ou o arquivo for inválido
        """
        self._validate(audio_path)
        pipeline = self._get_pipeline()

        try:
            kwargs: dict = {}
            if self._num is not None:
                kwargs["num_speakers"] = self._num
            else:
                kwargs["min_speakers"] = self._min
                kwargs["max_speakers"] = self._max

            diarization = pipeline(audio_path, **kwargs)  # type: ignore
            return self._parse(diarization)

        except Exception as e:
            raise TranscriptionError(
                f"Pyannote diarization falhou: {str(e)}\n"
                "Verifique HUGGINGFACE_TOKEN e acesso ao modelo."
            ) from e

    # ------------------------------------------------------------------
    # Privados
    # ------------------------------------------------------------------

    def _get_pipeline(self):
        """Carrega o pipeline pyannote uma única vez (lazy loading)."""
        if self._pipeline is not None:
            return self._pipeline

        # Verifica se pyannote.audio está instalado
        try:
            from pyannote.audio import Pipeline
        except ImportError:
            raise TranscriptionError(
                "pyannote.audio não instalado.\n"
                "Execute: pip install pyannote.audio"
            )

        # Verifica se torch está instalado
        try:
            import torch
        except ImportError:
            raise TranscriptionError(
                "torch não instalado.\n"
                "Execute: pip install torch"
            )

        # Carrega o modelo do HuggingFace e move para o device configurado
        try:
            self._pipeline = Pipeline.from_pretrained(
                self.MODEL_ID,
                token=self._hf_token,  # use_auth_token depreciado >= 3.0
            )
            self._pipeline.to(torch.device(self._device))  # type: ignore
        except Exception as e:
            raise TranscriptionError(
                f"Não foi possível carregar o modelo pyannote: {str(e)}\n"
                "Verifique o token e se aceitou os termos em:\n"
                "hf.co/pyannote/speaker-diarization-3.1"
            ) from e

        return self._pipeline
# 
    def _validate(self, audio_path: str) -> None:
        if not Path(audio_path).exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {audio_path}")

    def _parse(self, diarization) -> list[DiarizationSegment]:
        """Converte saída do pyannote em lista de DiarizationSegment."""
        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append(DiarizationSegment(
                start=round(turn.start, 3),
                end=round(turn.end, 3),
                speaker=speaker,  # "SPEAKER_00", "SPEAKER_01", ...
            ))
        return sorted(segments, key=lambda s: s.start)
    
