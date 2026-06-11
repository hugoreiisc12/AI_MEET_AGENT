"""
process_audio_to_json.py

Script que:
  1. Transcreve áudio
  2. Gera resumo com IA
  3. Exporta tudo como JSON estruturado
  4. Abre chat para consultar
"""

import sys
import json
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from domain.entities.meeting import Meeting
from presentation.container import get_container
from use_cases.transcribe_meeting import TranscribeMeetingInput
from use_cases.summarize_meeting import SummarizeMeetingInput
from use_cases.chat_with_meeting import ChatWithMeetingInput


def process_audio_to_json(audio_path: str, output_json: str = None) -> dict:
    """
    Processa áudio completo e retorna JSON estruturado.
    
    Args:
        audio_path: Caminho do áudio
        output_json: Caminho para salvar JSON (opcional)
    
    Returns:
        dict com dados da reunião estruturados
    """
    if output_json is None:
        output_json = f"data/meetings/meeting_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    container = get_container()
    
    print("\n🎤 Meet Agent — Processamento de Áudio para JSON")
    print("=" * 60)
    
    # 1. Transcrição
    print(f"\n[1/3] 🎙️  Transcrevendo: {audio_path}")
    t_result = container.transcribe_meeting.execute(
        TranscribeMeetingInput(audio_path=audio_path, with_diarization=True)
    )
    if not t_result.success:
        print(f"  ❌ Erro: {t_result.error_message}")
        sys.exit(1)
    
    transcript = t_result.transcript
    print(f"  ✅ Transcrição concluída — {transcript.duration_minutes:.1f} min")
    print(f"     Speakers: {transcript.speakers}")
    
    # 2. Cria entidade Meeting
    meeting = Meeting(
        id=str(uuid.uuid4()),
        title=f"Reunião {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        transcript_text=transcript.full_text,
        transcript_formatted=transcript.formatted,
        participants=transcript.speakers,
        duration_minutes=transcript.duration_minutes,
        audio_path=audio_path,
    )
    
    # 3. Resumo
    print("\n[2/3] 🤖 Gerando resumo com IA...")
    s_result = container.summarize_meeting.execute(
        SummarizeMeetingInput(meeting=meeting)
    )
    if not s_result.success:
        print(f"  ❌ Erro: {s_result.error_message}")
        sys.exit(1)
    
    meeting.summary = s_result.summary
    print(f"  ✅ Resumo gerado com sucesso")
    
    # 4. Estrutura JSON
    meeting_json = {
        "id": meeting.id,
        "title": meeting.title,
        "timestamp": meeting.started_at.isoformat(),
        "duration_minutes": meeting.duration_minutes,
        "participants": meeting.participants or [],
        "transcript": {
            "full_text": meeting.transcript_text,
            "formatted": meeting.transcript_formatted,
            "speakers_count": len(meeting.participants or []),
        },
        "summary": {
            "overview": meeting.summary.overview if meeting.summary else None,
            "topics": meeting.summary.topics if meeting.summary else [],
            "tasks": [
                {
                    "description": task.description,
                    "responsible": task.responsible,
                    "deadline": task.deadline,
                    "done": task.done,
                }
                for task in (meeting.summary.tasks if meeting.summary else [])
            ],
            "decisions": [
                {
                    "description": decision.description,
                    "context": decision.context,
                }
                for decision in (meeting.summary.decisions if meeting.summary else [])
            ],
            "formatted": meeting.summary.formatted if meeting.summary else None,
        },
        "audio_path": meeting.audio_path,
    }
    
    # 5. Salva JSON
    Path(output_json).parent.mkdir(parents=True, exist_ok=True)
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(meeting_json, f, ensure_ascii=False, indent=2)
    
    print(f"\n[3/3] 💾 JSON salvo em: {output_json}")
    print("=" * 60)
    
    return meeting_json, meeting


def interactive_chat(meeting):
    """Loop de chat interativo com a reunião."""
    container = get_container()
    history = []
    
    print("\n💬 Chat ativo — Pergunte sobre a reunião")
    print("   (Digite 'sair' ou pressione Ctrl+C para encerrar)\n")
    
    while True:
        try:
            question = input("Você: ").strip()
            
            if question.lower() in ["sair", "exit", "quit"]:
                print("\n✅ Chat encerrado. Até logo!")
                break
                
            if not question:
                continue
            
            c_result = container.chat_with_meeting.execute(
                ChatWithMeetingInput(
                    meeting=meeting,
                    question=question,
                    history=history,
                )
            )
            
            if c_result.success:
                print(f"\n🤖 Agente: {c_result.answer}\n")
                history.append({"role": "user", "content": question})
                history.append({"role": "assistant", "content": c_result.answer})
            else:
                print(f"\n❌ Erro: {c_result.error_message}\n")
        
        except KeyboardInterrupt:
            print("\n\n✅ Chat interrompido. Até logo!")
            break


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Processa áudio para JSON e permite chat"
    )
    parser.add_argument("audio_path", help="Caminho do arquivo de áudio")
    parser.add_argument(
        "--output",
        "-o",
        help="Caminho do arquivo JSON de saída (padrão: data/meetings/meeting_YYYYMMDD_HHMMSS.json)"
    )
    parser.add_argument(
        "--no-chat",
        action="store_true",
        help="Apenas processa sem abrir chat"
    )
    
    args = parser.parse_args()
    
    # Processa áudio
    meeting_json, meeting = process_audio_to_json(args.audio_path, args.output)
    
    # Chat interativo (opcional)
    if not args.no_chat:
        interactive_chat(meeting)
    else:
        print("\n📄 JSON processado. Nenhum chat aberto (use sem --no-chat para chat).")
        print(f"\n📋 Resumo:\n{meeting.summary.formatted if meeting.summary else 'N/A'}")
