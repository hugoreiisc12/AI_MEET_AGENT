"""
bot_setup.py — Autenticação inicial do bot (rodar UMA única vez).

Cria/atualiza o perfil Chrome persistente com login manual.
Nunca automatiza credenciais — o Google detecta e bloqueia.

Uso:
    python infrastructure/recorder/bot_setup.py

Configuração necessária no .env:
    BOT_CHROME_PROFILE=./bot_chrome_profile
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from config.settings import get_settings


async def main():
    settings = get_settings()
    profile_dir = str(settings.bot_chrome_profile)

    print("\n" + "=" * 60)
    print("  Meet Agent Bot — Setup de Autenticação")
    print("=" * 60)
    print(f"  Perfil: {profile_dir}")
    print()
    print("  Uma janela do Chrome será aberta.")
    print("  Faça login MANUALMENTE com a conta DEDICADA do bot.")
    print("  Se houver 2FA, complete na janela.")
    print("=" * 60)

    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=False,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://accounts.google.com")

        print("\n>>> Faça login na janela aberta.")
        print(">>> Quando terminar, volte aqui e pressione Enter.\n")
        input()

        await page.goto("https://meet.google.com")
        await asyncio.sleep(3)

        if "accounts.google.com" in page.url:
            print("\nFALHA: Ainda não logado. Rode o setup novamente.")
            print("Certifique-se de completar o login na janela do Chrome.\n")
        else:
            print(f"\nOK! Sessão salva no perfil: {profile_dir}")
            print("O bot está pronto para usar.\n")

        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
