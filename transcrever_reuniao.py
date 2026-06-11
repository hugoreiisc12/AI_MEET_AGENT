"""
Script para transcrever um arquivo de áudio e salvar no MongoDB.
Uso: python transcrever_reuniao.py <caminho_do_audio>
"""
import sys
import os
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from config.settings import get_settings
from presentation.container import get_container
from domain.entities.meeting import Meeting
from use_cases.transcribe_meeting import TranscribeMeetingInput
from use_cases.summarize_meeting import SummarizeMeetingInput

if len(sys.argv) < 2:
    print("Uso: python transcrever_reuniao.py <caminho_do_audio>")
    sys.exit(1)

AUDIO_PATH = sys.argv[1]

settings = get_settings()
container = get_container()

print(f"Modo: {'MongoDB' if settings.use_mongo else 'outro'}")
print(f"Arquivo: {AUDIO_PATH}")

# 1. Transcrever
print("\n[1/3] Transcrevendo áudio com Whisper...")
t_result = container.transcribe_meeting.execute(
    TranscribeMeetingInput(audio_path=AUDIO_PATH, with_diarization=True)
)
if not t_result.success:
    print(f"Erro na transcrição: {t_result.error_message}")
    sys.exit(1)

transcript = t_result.transcript
print(f"Transcrição concluída — {transcript.duration_minutes:.1f} min")
print(f"Speakers: {transcript.speakers}")

# 2. Montar Meeting
meeting = Meeting(
    id=str(uuid.uuid4()),
    title=f"Reunião {datetime.now().strftime('%d/%m/%Y %H:%M')}",
    transcript_text=transcript.full_text,
    transcript_formatted=transcript.formatted,
    participants=transcript.speakers,
    duration_minutes=transcript.duration_minutes,
    audio_path=AUDIO_PATH,
)

print(f"\nMeeting ID: {meeting.id}")

# 3. Resumo
print("\n[2/3] Gerando resumo com IA (Ollama)...")
s_result = container.summarize_meeting.execute(
    SummarizeMeetingInput(meeting=meeting)
)
if not s_result.success:
    print(f"Erro no resumo: {s_result.error_message}")
    sys.exit(1)

meeting.summary = s_result.summary
print("Resumo gerado com sucesso!")

# 4. Salvar no MongoDB
print("\n[3/3] Salvando no MongoDB...")
try:
    container.repository.save(meeting)
    print(f"Reunião salva no MongoDB com ID: {meeting.id}")
except Exception as e:
    print(f"Erro ao salvar no MongoDB: {e}")
    sys.exit(1)

print("\n✅ Processo concluído! A reunião já está disponível na interface.")
print(f"   Meeting ID: {meeting.id}")
