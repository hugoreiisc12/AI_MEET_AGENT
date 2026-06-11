"""
bot_setup.py — Autenticacao automatica do bot (rodar UMA unica vez).

Usa undetected-chromedriver para fazer login sem ser bloqueado pelo Google.
O perfil salvo em bot_chrome_profile e reutilizado pelo Playwright nas
execucoes seguintes (S1).
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def main():
    from dotenv import load_dotenv
    load_dotenv()

    email = os.getenv("BOT_GOOGLE_EMAIL", "")
    password = os.getenv("BOT_GOOGLE_PASSWORD", "")
    profile_dir = os.getenv("BOT_CHROME_PROFILE", "./bot_chrome_profile")

    if not email or not password:
        print("\nConfigure no .env:")
        print("   BOT_GOOGLE_EMAIL=seubot@gmail.com")
        print("   BOT_GOOGLE_PASSWORD=sua_senha")
        sys.exit(1)

    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    print("\nMeet Agent Bot - Setup de autenticacao")
    print(f"   Email: {email}")
    print(f"   Perfil: {profile_dir}")
    print("=" * 50)

    os.makedirs(profile_dir, exist_ok=True)

    options = uc.ChromeOptions()
    options.add_argument(f"--user-data-dir={os.path.abspath(profile_dir)}")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = uc.Chrome(options=options)
    driver.set_page_load_timeout(30)

    try:
        print("\nNavegando para login do Google...")
        driver.get("https://accounts.google.com/signin")
        time.sleep(2)

        print("Preenchendo email...")
        email_field = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="email"]'))
        )
        email_field.send_keys(email)
        time.sleep(0.5)
        driver.find_element(By.ID, "identifierNext").click()
        time.sleep(3)

        print("Preenchendo senha...")
        password_field = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="password"]'))
        )
        password_field.send_keys(password)
        time.sleep(0.5)
        driver.find_element(By.ID, "passwordNext").click()
        time.sleep(3)

        print("\nAguardando conclusao do login...")
        wait = WebDriverWait(driver, 180)
        wait.until(lambda d: "myaccount.google.com" in d.current_url or
                  ("google.com" in d.current_url and "signin" not in d.current_url))

        print("Login realizado com sucesso!")
        print(f"Perfil salvo em: {profile_dir}")

    except Exception as e:
        print(f"\nAtencao - Erro na automacao: {e}")
        print("   O navegador pode ter solicitado verificacao em 2 etapas.")
        print("   Complete manualmente e pressione Enter...")
        try:
            input()
        except EOFError:
            pass
        print("Continuando...")

    finally:
        time.sleep(2)
        driver.quit()
        print("Browser fechado. Perfil pronto para uso.")


if __name__ == "__main__":
    main()
