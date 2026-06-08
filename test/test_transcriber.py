# Camada de testes paea validação do WhisperTranscriber.

"""
Script de validação do WhisperLocalTranscriber.

Antes de rodar o script, verificar:
  1. pip install -r requirements.txt
  2. pip install openai-whisper torch
"""
# Adciona o diretorio atual ao sys.path oara mentir a compatibilidade de imports 
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from infrastructure.transcriber.whisper_local_transcriber import WhisperLocalTranscriber
from use_cases.transcribe_meeting import TranscribeMeetingUC, TranscribeMeetingInput

import pytest


# ── Testes de integração (requerem áudio real + OPENAI_API_KEY) ───────────
# Executar manualmente: python test/test_transcriber.py <audio.wav>

@pytest.mark.skip(reason="Requer arquivo de áudio real e openai-whisper instalado")
def test_transcricao_simples() -> None:
    _run_simple_transcription()


@pytest.mark.skip(reason="Requer arquivo de áudio real e openai-whisper instalado")
def test_transcricao_com_diarizacao() -> None:
    _run_diarized_transcription()


def _run_simple_transcription(audio_path: str | None = None) -> None:
    if not audio_path:
        return
    print("\n--- Teste 1: Transcrição simples ---")
    transcriber = WhisperLocalTranscriber()
    uc = TranscribeMeetingUC(transcriber=transcriber)

    result = uc.execute(
        TranscribeMeetingInput(audio_path=audio_path, with_diarization=False)
    )

    if result.success:
        t = result.transcript
        print(f"Idioma detectado : {t.language}")
        print(f"Duração estimada : {t.duration_minutes:.1f} min")
        print(f"Texto completo   :\n{t.full_text[:500]}...")
    else:
        print(f"ERRO: {result.error_message}")


def _run_diarized_transcription(audio_path: str | None = None) -> None:
    if not audio_path:
        return
    print("\n--- Teste 2: Transcrição com diarização ---")
    transcriber = WhisperLocalTranscriber()
    uc = TranscribeMeetingUC(transcriber=transcriber)

    result = uc.execute(
        TranscribeMeetingInput(audio_path=audio_path, with_diarization=True)
    )

    if result.success:
        t = result.transcript
        print(f"Speakers detectados : {t.speakers}")
        print(f"Total de segmentos  : {len(t.segments)}")
        print("\nPrimeiros 5 segmentos:")
        for seg in t.segments[:5]:
            print(f"  {seg}")
    else:
        print(f"ERRO: {result.error_message}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python test_transcriber.py <caminho_do_audio.wav>")
        print("\nDica: grave qualquer áudio de teste de 1-2 min para validar.")
        sys.exit(1)

    audio = sys.argv[1]
    _run_simple_transcription(audio)
    _run_diarized_transcription(audio)
