"""
Abre um Chrome visível para login manual (ou confirmação de 2FA).
O perfil é salvo localmente e reutilizado nas próximas execuções.

Após login bem-sucedido, envia um e-mail de confirmação para
NOTIFICATION_EMAIL.

Configurações necessárias no .env:
    BOT_GOOGLE_EMAIL=seubot@gmail.com
    BOT_GOOGLE_PASSWORD=senha_da_conta
    BOT_SMTP_APP_PASSWORD=xxxx xxxx xxxx xxxx   ← App Password do Gmail
    NOTIFICATION_EMAIL=voce@email.com            ← seu e-mail pessoal
    BOT_CHROME_PROFILE=./bot_chrome_profile      ← opcional
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))


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
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )

        page = await context.new_page()
        await page.goto(
            "https://accounts.google.com/signin",
            wait_until="networkidle",
        )

        # Já está logado — pula direto para notificação
        if "myaccount.google.com" in page.url:
            print("\n✅ Já está autenticado! Nenhuma ação necessária.")
            await context.close()
            _send_alive_notification(email)
            return

        print("\n📋 Preenchendo credenciais automaticamente...")

        try:
            await page.wait_for_selector('input[type="email"]', timeout=10_000)
            await page.fill('input[type="email"]', email)
            await page.click('#identifierNext')
            await asyncio.sleep(2)

            await page.wait_for_selector(
                'input[type="password"]', state="visible", timeout=10_000
            )
            await page.fill('input[type="password"]', password)
            await page.click('#passwordNext')

            print("\n⏳ Aguardando conclusão do login...")
            print("   Se aparecer verificação em 2 etapas, complete no browser.")
            print("   O script aguardará até você concluir.\n")

        except Exception as e:
            print(f"\n⚠️  Erro ao preencher automaticamente: {e}")
            print("   Complete o login manualmente no browser.\n")

        try:
            await page.wait_for_url(
                "**/myaccount.google.com**",
                timeout=120_000,
            )
            print("✅ Login realizado com sucesso!")
            print(f"✅ Perfil salvo em: {profile_dir}")
            print("\n🎉 Setup concluído! O bot está pronto para usar.")

            # ── Notificação de vida ──────────────────────────────────────
            await context.close()          # fecha o browser antes de enviar
            _send_alive_notification(email)
            # ─────────────────────────────────────────────────────────────
            return

        except Exception:
            print("\n⚠️  Timeout. Tente novamente ou verifique as credenciais.")

        finally:
            await asyncio.sleep(2)
            try:
                await context.close()
            except Exception:
                pass


def _send_alive_notification(bot_email: str) -> None:
    """Envia o e-mail 'Estou vivo' após login confirmado."""
    try:
        from config.settings import get_settings
        enabled = get_settings().enable_email
    except Exception:
        enabled = False

    if not enabled:
        print("(Notificação por e-mail desabilitada via settings.enable_email.)")
        return

    try:
        from utils.email_notifier import build_config_from_env, notify_bot_alive

        config = build_config_from_env()
        notify_bot_alive(config)
        print(f"📧 E-mail de notificação enviado para {config.to_email}")

    except ValueError as e:
        # Variáveis de e-mail não configuradas — avisa mas não quebra o setup
        print(f"\n⚠️  Notificação por e-mail não configurada: {e}")
        print("   O bot está autenticado e pronto. Configure o .env para receber e-mails.")

    except Exception as e:
        print(f"\n⚠️  Falha ao enviar e-mail de notificação: {e}")
        print("   Verifique se BOT_SMTP_APP_PASSWORD está correto.")


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