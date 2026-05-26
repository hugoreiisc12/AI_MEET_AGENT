"""
 Execute UMA VEZ para autenticar o bot no Google.

Este script abre um Chrome visível para você fazer o login manualmente
(ou confirmar verificação em duas etapas). O perfil é salvo localmente
e nas próximas execuções o login é automático.


depis que concluir:
    O arquivo ./bot_chrome_profile/ conterá o perfil autenticado.
    O bot não precisará fazer login novamente.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

# Importa as configurações para acessar as variaveis de ambiente 
async def setup_bot_profile(
    email: str,
    password: str,
    profile_dir: str = "./bot_chrome_profile",
) -> None:
    from playwright.async_api import async_playwright

    print("\n🤖 Meet Agent Bot — Setup de autenticação")
    print("=" * 50)
    print(f"Email: {email}")
    print(f"Perfil: {profile_dir}")
    print("=" * 50)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=False,               # visível para você interagir
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )

        page = await context.new_page()

        # Navega para o login do Google
        await page.goto(
            "https://accounts.google.com/signin",
            wait_until="networkidle",
        )

        # Verifica se já está logado
        if "myaccount.google.com" in page.url:
            print("\n✅ Já está autenticado! Nenhuma ação necessária.")
            await context.close()
            return

        print("\n📋 Preencha o email automaticamente...")

        # Preenche email e senha, mas se der erro, o usuario que pode preecher manualmente 
        try:
            await page.wait_for_selector('input[type="email"]', timeout=10000)
            await page.fill('input[type="email"]', email)
            await page.click('#identifierNext')
            await asyncio.sleep(2)

            # Preenche senha
            await page.wait_for_selector(
                'input[type="password"]', state="visible", timeout=10000
            )
            await page.fill('input[type="password"]', password)
            await page.click('#passwordNext')

            print("\n⏳ Aguardando conclusão do login...")
            print("   Se aparecer verificação em 2 etapas, complete no browser.")
            print("   O script aguardará até você concluir.\n")

        except Exception as e:
            print(f"\n⚠️  Erro ao preencher automaticamente: {e}")
            print("   Complete o login manualmente no browser.\n")

        # Aguarda o usuário concluir o login (com ou sem 2FA) e redirecionar para a página de perfil
        try:
            await page.wait_for_url(
                "**/myaccount.google.com**",
                timeout=120000,  # 2 minutos para o usuário agir
            )
            print("✅ Login realizado com sucesso!")
            print(f"✅ Perfil salvo em: {profile_dir}")
            print("\n🎉 Setup concluído! O bot está pronto para usar.")

        except Exception:
            print("\n⚠️  Timeout. Tente novamente ou verifique as credenciais.")

        finally:
            # Dá tempo para salvar o perfil
            await asyncio.sleep(2)
            await context.close()

# Roda o setup do bot para autenticar e salvar o perfil localmente 
def main():
    from dotenv import load_dotenv
    load_dotenv()

    email    = os.getenv("BOT_GOOGLE_EMAIL", "")
    password = os.getenv("BOT_GOOGLE_PASSWORD", "")
    profile  = os.getenv("BOT_CHROME_PROFILE", "./bot_chrome_profile")

    if not email or not password:
        print("\n❌ Configure no .env:")
        print("   BOT_GOOGLE_EMAIL=seubot@gmail.com")
        print("   BOT_GOOGLE_PASSWORD=sua_senha")
        sys.exit(1)

    asyncio.run(setup_bot_profile(email, password, profile))


if __name__ == "__main__":
    main()