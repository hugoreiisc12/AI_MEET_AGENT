"""
infraestrutura/trasncriber/whisper_with_diarization.py

Combina dois modelos:
  1. Whisper     → transcreve o que foi dito (texto + timestamps por segmento)
  2. Pyannote    → identifica quem falou quando (segmentos de speaker)

O alinhamento funciona assim:
  Para cada segmento do Whisper, encontra qual speaker do pyannote
  ocupa a maior sobreposição de tempo com aquele segmento.
  Resultado: texto preciso do Whisper com identidade real do pyannote.

Implementa ITranscriber — substitui WhisperTranscriber no container
quando USE_REAL_DIARIZATION=true no .env.
"""

from __future__ import annotations

from entities.transcript import Transcript, Segment
from interface.transcriber import ITranscriber, TranscriptionError
from diarização_reality.pyannote_diarizer import (
    PyannoteDiarizer,
    DiarizationSegment,
)
from infraestrutura.trasncriber.whisper_transcriber import WhisperTranscriber
from config.settings import get_settings


class WhisperWithDiarization(ITranscriber):
    """
    Implementação de ITranscriber com diarização real.
    
    Troca pseudo-diarizer (heurística de pausa) por identificação
    acústica real via pyannote, sem tocar em domain/ nem em user_cases/.
    """

    def __init__(
        self,
        whisper: ITranscriber | None = None,
        diarizer: PyannoteDiarizer | None = None,
    ) -> None:
        """
        Args:
            whisper:   Transcritor base (padrão: WhisperTranscriber)
            diarizer:  Diarizador (padrão: construído a partir do .env)
        """
        self._whisper = whisper or WhisperTranscriber()
        self._diarizer = diarizer or self._build_diarizer()

    # ── Interface pública (implementa ITranscriber) ──────────────────────

    def transcribe(self, audio_path: str) -> Transcript:
        """Transcrição simples sem diarização (delegando ao Whisper)."""
        return self._whisper.transcribe(audio_path)

    def transcribe_with_diarization(self, audio_path: str) -> Transcript:
        """
        Transcrição com diarização real.
        
        Fluxo:
        1. Whisper gera texto + timestamps por segmento
        2. Pyannote identifica speakers (segmentos de fala)
        3. Alinhamento por sobreposição de tempo
        """
        try:
            # 1. Transcrição base
            transcript = self._whisper.transcribe(audio_path)
            
            # Se não tem segmentos, cai no fallback do Whisper com diarização simples
            if not transcript.segments:
                return self._whisper.transcribe_with_diarization(audio_path)

            # 2. Diarização real
            try:
                diar_segments = self._diarizer.diarize(audio_path)
            except Exception as e:
                # Se diarização falhar, retorna transcrição sem diarização
                return self._whisper.transcribe_with_diarization(audio_path)

            # 3. Alinhamento
            aligned_segments = self._align(transcript.segments, diar_segments)

            return Transcript(
                full_text=transcript.full_text,
                segments=aligned_segments,
                language=transcript.language,
                audio_path=audio_path,
            )

        except Exception as e:
            raise TranscriptionError(
                f"WhisperWithDiarization falhou: {str(e)}"
            ) from e

    # ── Privados ──────────────────────────────────────────────────────

    def _align(
        self,
        whisper_segments: list[Segment],
        diar_segments: list[DiarizationSegment],
    ) -> list[Segment]:
        """
        Alinha segmentos do Whisper encontrando o speaker com maior
        sobreposição de tempo nos segmentos do pyannote.

        Complexidade: O(W × D) - aceitável para reuniões até 3h
        (Whisper ~200 segs, pyannote ~500 segs → 100k operações simples)

        Args:
            whisper_segments:  Segmentos com texto e timestamps do Whisper
            diar_segments:     Segmentos de speaker do pyannote

        Returns:
            Lista de Segment com speaker identificado
        """
        result = []

        for ws in whisper_segments:
            speaker = self._dominant_speaker(ws.start, ws.end, diar_segments)
            result.append(Segment(
                start=ws.start,
                end=ws.end,
                speaker=speaker,
                text=ws.text,
            ))

        return result

    def _dominant_speaker(
        self,
        seg_start: float,
        seg_end: float,
        diar_segments: list[DiarizationSegment],
    ) -> str:
        """
        Encontra o speaker do pyannote com maior sobreposição no intervalo
        [seg_start, seg_end].

        Se nenhum segmento do pyannote cobrir o intervalo, retorna "SPEAKER_00".

        Args:
            seg_start:      Início do segmento Whisper (em segundos)
            seg_end:        Fim do segmento Whisper (em segundos)
            diar_segments:  Lista de segmentos do pyannote

        Returns:
            ID do speaker (ex: "SPEAKER_00", "SPEAKER_01") ou "SPEAKER_00" se sem cobertura
        """
        overlap_by_speaker: dict[str, float] = {}

        for ds in diar_segments:
            # Calcula sobreposição entre [seg_start, seg_end] e [ds.start, ds.end]
            overlap_start = max(seg_start, ds.start)
            overlap_end = min(seg_end, ds.end)
            overlap = max(0.0, overlap_end - overlap_start)

            if overlap > 0:
                overlap_by_speaker[ds.speaker] = (
                    overlap_by_speaker.get(ds.speaker, 0.0) + overlap
                )

        if not overlap_by_speaker:
            return "SPEAKER_00"

        return max(overlap_by_speaker, key=overlap_by_speaker.get)

    @staticmethod
    def _build_diarizer() -> PyannoteDiarizer:
        """
        Constrói o diarizer a partir das configurações do .env.

        Raises:
            TranscriptionError: Se HUGGINGFACE_TOKEN não estiver configurado

        Returns:
            Instância configurada de PyannoteDiarizer
        """
        settings = get_settings()
        hf_token = getattr(settings, "huggingface_token", "")

        if not hf_token:
            raise TranscriptionError(
                "HUGGINGFACE_TOKEN não configurado.\n"
                "Adicione ao .env: HUGGINGFACE_TOKEN=hf_..."
            )

        return PyannoteDiarizer(
            hf_token=hf_token,
            device=getattr(settings, "diarization_device", "cpu"),
        )
