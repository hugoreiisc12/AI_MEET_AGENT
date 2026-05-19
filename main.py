"""
main.py — Ponto de entrada do Meet Agent.

Modos de uso:
  streamlit run main.py              → Interface web Streamlit
  python main.py --test <audio.wav>  → Teste via terminal (sem UI)
  python main.py --api               → Sobe FastAPI via uvicorn
  python main.py --worker            → Sobe Celery worker
  
"""
import sys
import os

# Garante que o root está no path independente de onde o script é chamado
sys.path.insert(0, os.path.dirname(__file__))


def run_streamlit() -> None:
    """Sobe a interface Streamlit."""
    import subprocess
    subprocess.run(
        [
            sys.executable, "-m", "streamlit", "run",
            "presetation/streamlit/app.py",
            "--server.headless", "false",
        ],
        check=True,
    )


def run_api() -> None:
    """Sobe a FastAPI via uvicorn."""
    import subprocess
    subprocess.run(
        [
            sys.executable, "-m", "uvicorn",
            "api.main:app",
            "--host", "0.0.0.0",
            "--port", "8000",
        ],
        check=True,
    )


def run_worker() -> None:
    """Sobe o Celery worker."""
    import subprocess
    subprocess.run(
        [
            sys.executable, "-m", "celery",
            "-A", "worker.tasks.celery_app",
            "worker",
            "--loglevel=info",
        ],
        check=True,
    )


def run_terminal_test(audio_path: str) -> None:
    """
    Executa o fluxo completo via terminal para validação rápida:
      1. Transcreve o áudio
      2. Gera o resumo
      3. Abre loop de chat interativo
    """
    import uuid
    from datetime import datetime
    from entities.meeting import Meeting
    from presentation.container import get_container
    from use_cases.transcribe_meeting import TranscribeMeetingInput
    from use_cases.summarize_meeting import SummarizeMeetingInput
    from use_cases.chat_with_meeting import ChatWithMeetingInput

    container = get_container()

    print("\n🎤 Meet Agent — Modo Terminal")
    print("=" * 50)

    print(f"\n[1/2] Transcrevendo: {audio_path}")
    t_result = container.transcribe_meeting.execute(
        TranscribeMeetingInput(audio_path=audio_path, with_diarization=True)
    )
    if not t_result.success:
        print(f"❌ Erro: {t_result.error_message}")
        sys.exit(1)

    transcript = t_result.transcript
    print(f"✅ Transcrição concluída — {transcript.duration_minutes:.1f} min")
    print(f"   Speakers: {transcript.speakers or ['Speaker 0']}")

    meeting = Meeting(
        id=str(uuid.uuid4()),
        title=f"Reunião {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        transcript_text=transcript.full_text,
        transcript_formatted=transcript.formatted,
        participants=transcript.speakers,
        duration_minutes=transcript.duration_minutes,
        audio_path=audio_path,
    )

    print("\n[2/2] Gerando resumo com IA...")
    s_result = container.summarize_meeting.execute(
        SummarizeMeetingInput(meeting=meeting)
    )
    if not s_result.success:
        print(f"❌ Erro: {s_result.error_message}")
        sys.exit(1)

    meeting.summary = s_result.summary
    print("\n✅ Resumo gerado:\n")
    print(meeting.summary.formatted)

    print("\n" + "=" * 50)
    print("💬 Chat ativo — pergunte sobre a reunião (ctrl+c para sair)\n")
    history = []

    while True:
        try:
            question = input("Você: ").strip()
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
                print(f"\nAgente: {c_result.answer}\n")
                history.append({"role": "user", "content": question})
                history.append({"role": "assistant", "content": c_result.answer})
            else:
                print(f"\n⚠️ {c_result.error_message}\n")

        except KeyboardInterrupt:
            print("\n\nEncerrando. Até logo!")
            break


if __name__ == "__main__":
    if "--test" in sys.argv:
        idx = sys.argv.index("--test")
        if idx + 1 >= len(sys.argv):
            print("Uso: python main.py --test <caminho_do_audio.wav>")
            sys.exit(1)
        run_terminal_test(sys.argv[idx + 1])
    elif "--api" in sys.argv:
        run_api()
    elif "--worker" in sys.argv:
        run_worker()
    else:
        run_streamlit()