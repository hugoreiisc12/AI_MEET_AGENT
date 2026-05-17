# Camada de testes paea validação do WhisperTranscriber.

"""
Script de validação do WhisperTranscriber.

Antes de rodar o script, verificar:
  1. cp .env.example .env
  2. Edite .env com sua OPENAI_API_KEY
  3. pip install -r requirements.txt
"""
# Adciona o diretorio atual ao sys.path oara mentir a compatibilidade de imports 
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from infraestrutura.trasncriber.whisper_transcriber import WhisperTranscriber
from user_cases.transcribe_meeting import TranscribeMeetingUC, TranscribeMeetingInput

# Realiza um teste de basico de um arquivo de auddio sem diarização
def test_transcricao_simples(audio_path: str) -> None:
    print("\n--- Teste 1: Transcrição simples ---")
    transcriber = WhisperTranscriber() # Criaçao de instanciamento do WhisperTranscriber
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

# Teste de transcriação com diarização, verificando (identifica quem fala em cada momento)
def test_transcricao_com_diarizacao(audio_path: str) -> None:
    print("\n--- Teste 2: Transcrição com diarização ---")
    transcriber = WhisperTranscriber() # Criação de instanciamento do WhisperTranscriber 
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
    test_transcricao_simples(audio)
    test_transcricao_com_diarizacao(audio)
