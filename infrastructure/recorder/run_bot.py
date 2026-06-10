"""
run_bot.py — Entrypoint dedicado do bot (correção S5).

Processo separado do Streamlit para evitar loop infinito e problemas
de event loop no Windows. A UI acompanha via polling do JSON de status.

Uso:
    python -m infrastructure.recorder.run_bot --url "https://meet.google.com/abc-defg-hij"

Saída:
    Imprime o session_id na primeira linha do stdout (a UI captura).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bot gravador do Google Meet")
    p.add_argument("--url", required=True, help="Link da reunião do Meet")
    p.add_argument("--profile", default=None, help="Dir do perfil Chrome (override)")
    p.add_argument("--audio-dir", default=None, help="Dir de saída do áudio (override)")
    p.add_argument("--headless", action="store_true", help="Rodar sem janela")
    return p.parse_args()


async def main() -> int:
    args = parse_args()

    from config.settings import get_settings
    from infrastructure.recorder.playwright_bot_recorder import (
        BotNotLoggedInError,
        PlaywrightBotRecorder,
    )

    settings = get_settings()

    recorder = PlaywrightBotRecorder(
        chrome_profile_dir=args.profile or settings.bot_chrome_profile,
        audio_dir=args.audio_dir or settings.audio_storage_path,
        bot_name=settings.bot_name,
        headless=args.headless or settings.bot_headless,
        on_audio_ready=_make_delivery_callback(settings),
    )

    try:
        session = await recorder.join_async(args.url)
    except BotNotLoggedInError as exc:
        print(f"ERRO_LOGIN: {exc}", file=sys.stderr)
        return 2

    print(session.id)
    return 0


def _make_delivery_callback(settings):
    if getattr(settings, "app_mode", "solo") != "collab":
        return None

    async def deliver(audio_path, speaker_log_path):
        from worker.tasks import process_meeting_task
        process_meeting_task.delay(
            audio_path=str(audio_path),
            speaker_log_path=str(speaker_log_path) if speaker_log_path else None,
        )

    return deliver


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
