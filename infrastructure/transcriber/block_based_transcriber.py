"""
infrastructure/transcriber/block_based_transcriber.py

Processa áudio em blocos de 10s identificando o usuário real que falou.

Fluxo:
  1. Divide o áudio original em chunks de 10s via ffmpeg
  2. Transcreve cada chunk com Whisper local
  3. Identifica o speaker dominante no intervalo via speaker_observations
  4. Mapeia para o ID real do usuário (email/nome) via participant_info
  5. Retorna lista de SpeechBlock (quem, o que, como, quando)
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from domain.entities.speech_block import SpeechBlock
from interface.transcriber import TranscriptionError
from config.settings import get_settings


class BlockBasedTranscriber:
    """
    Transcritor por blocos de 10s com identificação de usuário real.

    Diferente do WhisperLocalTranscriber que transcreve tudo de uma vez
    e usa pseudo-diarização (Speaker 0/1), este transcritor:
    - Divide o áudio em janelas de 10s
    - Transcreve cada janela independentemente
    - Associa cada janela ao usuário real que estava falando
    """

    BLOCK_SIZE = 10  # segundos por bloco

    def __init__(self) -> None:
        self._settings = get_settings()

    def transcribe_blocks(
        self,
        audio_path: str,
        speaker_observations: list[dict[str, float | str]] | None = None,
        participant_info: dict[str, str] | None = None,
    ) -> list[SpeechBlock]:
        """
        Processa áudio em blocos de 10s associando cada um ao usuário real.

        Args:
            audio_path: Caminho do arquivo .webm gravado pelo bot
            speaker_observations: Amostras de speaker ativo coletadas durante a reunião
            participant_info: Mapeamento participant_id -> email/nome

        Returns:
            Lista de SpeechBlock com usuário real, texto e sentimento
        """
        audio_path_obj = Path(audio_path)
        if not audio_path_obj.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {audio_path}")

        duration = self._get_duration_seconds(audio_path)
        if duration <= 0:
            return []

        blocks: list[SpeechBlock] = []

        for start in range(0, int(duration), self.BLOCK_SIZE):
            end = min(start + self.BLOCK_SIZE, duration)

            chunk_text = self._transcribe_chunk(audio_path, start, end)
            if not chunk_text.strip():
                continue

            user_id = self._resolve_speaker(
                start, end,
                speaker_observations or [],
                participant_info or {},
            )

            blocks.append(SpeechBlock(
                user_id=user_id,
                text=chunk_text.strip(),
                start=float(start),
                end=float(end),
            ))

        return blocks

    def _get_duration_seconds(self, audio_path: str) -> float:
        """Obtém duração do áudio em segundos via ffprobe."""
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    audio_path,
                ],
                capture_output=True, text=True, timeout=30,
            )
            return float(result.stdout.strip())
        except Exception:
            return 0.0

    def _transcribe_chunk(self, audio_path: str, start: float, end: float) -> str:
        """
        Extrai um trecho do áudio via ffmpeg e transcreve com Whisper.

        Cria um arquivo WAV temporário para o trecho e chama o Whisper local.
        """
        import whisper_local_transcriber as whisper

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            chunk_path = tmp.name

        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", audio_path,
                    "-ss", str(start),
                    "-to", str(end),
                    "-vn",
                    "-acodec", "pcm_s16le",
                    "-ar", "16000",
                    "-ac", "1",
                    chunk_path,
                ],
                capture_output=True, text=True, timeout=60,
                check=True,
            )

            model = whisper.load_model(
                self._settings.whisper_model,
                device=self._settings.whisper_device,
            )
            result = model.transcribe(
                chunk_path,
                language=self._settings.whisper_language or None,
                verbose=False,
            )
            return result.get("text", "")

        except subprocess.CalledProcessError as e:
            raise TranscriptionError(
                f"Falha ao extrair trecho {start}-{end}s: {e.stderr}"
            ) from e
        except Exception as e:
            raise TranscriptionError(
                f"Falha ao transcrever trecho {start}-{end}s: {str(e)}"
            ) from e
        finally:
            try:
                os.unlink(chunk_path)
            except OSError:
                pass

    def _resolve_speaker(
        self,
        block_start: float,
        block_end: float,
        speaker_observations: list[dict[str, float | str]],
        participant_info: dict[str, str],
    ) -> str:
        """
        Determina o usuário real que falou durante o bloco de 10s.

        Estratégia:
          1. Filtra observações dentro do intervalo [block_start, block_end)
          2. Voto majoritário: participant_id mais frequente no bloco
          3. Mapeia participant_id -> email/nome real via participant_info
          4. Se não houver observações ou mapeamento, retorna 'Desconhecido'
        """
        participant_ids: Counter[str] = Counter()

        for obs in speaker_observations:
            ts = obs.get("timestamp")
            pid = obs.get("participant_id")
            if ts is None or not pid or not isinstance(pid, str):
                continue
            try:
                ts = float(ts)
            except (TypeError, ValueError):
                continue
            if block_start <= ts < block_end:
                participant_ids[pid] += 1

        if not participant_ids:
            return "Desconhecido"

        best_participant = participant_ids.most_common(1)[0][0]
        return participant_info.get(best_participant, best_participant)

    def blocks_to_transcript_data(
        self,
        blocks: list[SpeechBlock],
    ) -> dict:
        """
        Converte blocos em dados compatíveis com a entidade Meeting.

        Returns:
            dict com full_text, formatted, speakers, duration_minutes
        """
        full_text = " ".join(b.text for b in blocks)
        speakers = list(dict.fromkeys(b.user_id for b in blocks))

        formatted_lines = []
        for b in blocks:
            minutes = int(b.start // 60)
            seconds = int(b.start % 60)
            formatted_lines.append(
                f"[{minutes:02d}:{seconds:02d}] {b.user_id}: {b.text}"
            )

        return {
            "full_text": full_text,
            "formatted": "\n".join(formatted_lines),
            "speakers": speakers,
            "duration_minutes": round(
                (blocks[-1].end if blocks else 0) / 60, 1
            ),
        }
