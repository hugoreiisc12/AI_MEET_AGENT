# Ponto de entrada do Meet Agent, que decide o modo de execução ( UI Streamlit ou teste via terminal)

import sys
import os

"""
main.py — Ponto de entrada do Meet Agent.

Modos de uso:
  streamlit run main.py              → Interface web Streamlit
  python main.py --test <audio.wav>  → Teste via terminal (sem UI)
"""

# Garante que o root está no path independente de onde o script é chamado
sys.path.insert(0, os.path.dirname(__file__))

# Importações locais (após ajustar o path)
def run_streamlit() -> None:
    """Sobe a interface Streamlit."""
    import subprocess
    subprocess.run(
        [
            sys.executable, "-m", "streamlit", "run",
            "presentation/streamlit/app.py",
            "--server.headless", "false",
        ],
        check=True,
    )

# Teste via terminal, que executa o fluxo completo de transcrição, 
# resumo e chat interativo, permitindo validação rápida sem UI
def run_terminal_test(audio_path: str) -> None:
    """
    Executa o fluxo completo via terminal para validação rápida:
      1. Transcreve o áudio
      2. Gera o resumo
      3. Abre loop de chat interativo
    """

# Importações locais necessárias para teste via terminal (após ajustar o path) 
    import uuid
    from datetime import datetime
    from domain.entities.meeting import Meeting
    from presentation.container import get_container
    from use_cases.transcribe_meeting import TranscribeMeetingInput
    from use_cases.summarize_meeting import SummarizeMeetingInput
    from use_cases.chat_with_meeting import ChatWithMeetingInput

    container = get_container()

    print("\n🎤 Meet Agent — Modo Terminal")
    print("=" * 50)

 # 1. Transcrição do audio, que chama o processo de transcrição passando o caminho do Audio, 
 # e captura ativamente erros relacionados á transcrição
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

 # 2. Resumo da reunião, que chama o processo de summarização passando a reunião com transcrição anexada 
 # e captura ativamente erros relacionados a LLM 
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

    meeting = s_result.meeting
    summary = meeting.summary
    print("\n✅ Resumo gerado:\n")
    print(summary.formatted)

# 3. Chat interativo com reunião que entra em logo de perguntas e respostas a partir do contexto da reunião e do historico de conversa, permitindo ao usuario fazer perguntas sobre a reuninão e obter respostas do LLM
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
    else:
        run_streamlit()