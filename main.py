"""
main.py — Ponto de entrada do Meet Agent.

Modos de uso:
  (interface)                        → frontend/ (React): `cd frontend && npm run dev`, ou o container `web` no compose
  python main.py --test <audio.wav>  → Teste via terminal (sem UI)
  python main.py --api               → Sobe FastAPI via uvicorn
  python main.py --worker [FILAS]    → Worker de processamento (Celery); FILAS = transcribe,llm (padrão)
  python main.py --bot-worker        → Worker do bot (fila "bot", uma reunião por vez)
                                       Vários bots: um processo por perfil, BOT_CHROME_PROFILE=<pasta>
"""

import sys
import os
import subprocess

sys.path.insert(0, os.path.dirname(__file__))


def run_api() -> None:
    """Sobe a FastAPI via uvicorn."""
    from config.settings import get_settings
    os.environ.setdefault("SERVICE_NAME", "api")
    subprocess.run(
        [
            sys.executable, "-m", "uvicorn",
            "api.main:app",
            "--host", "0.0.0.0",
            "--port", str(get_settings().api_port),
            # Vários processos: cada um com seu pool de threads (ADR-015)
            "--workers", str(get_settings().api_workers),
        ],
        check=True,
    )


def run_worker(bot: bool = False, queues: str = "transcribe,llm") -> None:
    """Sobe um worker Celery: processamento (padrão) ou bot."""
    from pathlib import Path
    from config.settings import get_settings
    cmd = [
        sys.executable, "-m", "celery",
        "-A", "worker.tasks.celery_app",
        "worker",
        "--loglevel=info",
        # Sem a troca de mensagens entre workers: com pool solo, worker ocupado não responde e o
        # Celery enchia o log de "missed heartbeat"/"clocks out of sync". A saúde usa o batimento
        # próprio (infrastructure/observability.py), não isso.
        "--without-gossip", "--without-mingle", "--without-heartbeat",
    ]
    # pool=solo: um trabalho por processo. Paralelismo = mais processos (ADR-015): o Whisper
    # carrega o modelo uma vez e não convive bem com fork, e o navegador do bot roda no
    # processo principal.
    if bot:
        # Um perfil do Chrome por bot: o nome do nó vem da pasta do perfil
        profile = Path(get_settings().bot_chrome_profile).resolve().name
        cmd += ["-Q", "bot", "--pool=solo", "-n", f"bot-{profile}@%h"]
    else:
        cmd += ["-Q", queues, "--pool=solo", "-n", f"{queues.replace(',', '-')}@%h"]
    # O worker do bot confere a conta do Google ao subir (worker.tasks._check_bot_account).
    env = {**os.environ, "SERVICE_NAME": "bot" if bot else f"worker-{queues.replace(',', '-')}",
           "WORKER_QUEUES": "bot" if bot else queues}  # batimento (observabilidade)
    if bot:
        env["MEET_AGENT_BOT_WORKER"] = "1"
    subprocess.run(cmd, check=True, env=env)


def run_terminal_test(audio_path: str) -> None:
    """
    Executa o fluxo completo via terminal:
      1. Transcreve o áudio
      2. Gera o resumo
      3. Abre loop de chat interativo
    """
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

    # 1. Transcrição
    print(f"\n[1/2] Transcrevendo: {audio_path}")
    t_result = container.transcribe_meeting.execute(
        TranscribeMeetingInput(audio_path=audio_path, with_diarization=True)
    )
    if not t_result.success:
        print(f" Erro: {t_result.error_message}")
        sys.exit(1)

    transcript = t_result.transcript
    print(f" Transcrição concluída — {transcript.duration_minutes:.1f} min")
    print(f"   Speakers: {transcript.speakers or ['Speaker 0']}")

    # 2. Monta Meeting
    meeting = Meeting(
        id=str(uuid.uuid4()),
        title=f"Reunião {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        transcript_text=transcript.full_text,
        transcript_formatted=transcript.formatted,
        participants=transcript.speakers,
        duration_minutes=transcript.duration_minutes,
        audio_path=audio_path,
        # started_at tem default_factory=datetime.now na entity, não precisa passar
    )

    # 3. Resumo
    print("\n[2/2] Gerando resumo com IA...")
    s_result = container.summarize_meeting.execute(
        SummarizeMeetingInput(meeting=meeting)
    )
    if not s_result.success:
        print(f" Erro: {s_result.error_message}")
        sys.exit(1)

    # FIX: era `meeting = s_result.meeting` — SummarizeMeetingUC não devolve
    # o meeting em s_result.meeting; ele anexa o resumo diretamente em
    # meeting.summary (o objeto que passamos). Usar s_result.meeting causaria
    # AttributeError se o campo for None, e perderia o meeting já construído.
    meeting.summary = s_result.summary

    print("\n Resumo gerado:\n")
    # FIX: era `meeting.summary.formatted` — Summary.formatted é uma @property
    # que retorna str, não um atributo direto. Funciona, mas só após a linha
    # acima estar correta. Se s_result.meeting fosse None, teria quebrado antes.
    print(meeting.summary.formatted)

    # 4. Chat interativo
    print("\n" + "=" * 50)
    print(" Chat ativo — pergunte sobre a reunião (Ctrl+C para sair)\n")
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
                print(f"\n {c_result.error_message}\n")

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
    elif "--bot-worker" in sys.argv:
        run_worker(bot=True)
    elif "--worker" in sys.argv:
        idx = sys.argv.index("--worker")
        rest = sys.argv[idx + 1:]
        run_worker(queues=rest[0] if rest and not rest[0].startswith("-") else "transcribe,llm")
    else:
        print(__doc__)
        sys.exit(1)