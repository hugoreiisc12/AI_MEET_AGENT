"""Login no modo solo: o JsonAuthStore cumpre o contrato do MongoAuthStore usado pelo AuthService."""
import pytest

from infrastructure.auth_store import JsonAuthStore
from use_cases.auth import AuthError, AuthService


def test_cadastro_login_token_e_logout(tmp_path):
    path = tmp_path / "auth.json"
    auth = AuthService(JsonAuthStore(str(path)))

    ana = auth.register("Ana", "Ana@Empresa.com", "senha-forte")
    assert ana.email == "ana@empresa.com"
    with pytest.raises(AuthError):
        auth.register("Outra", "ana@empresa.com", "senha-forte")

    token, user = auth.login("ana@empresa.com", "senha-forte")
    assert user.id == ana.id

    # Outro processo (ou a API reiniciada) lê o mesmo arquivo: sessão e datas sobrevivem.
    again = AuthService(JsonAuthStore(str(path)))
    assert again.user_for_token(token).id == ana.id

    again.logout(token)
    assert auth.user_for_token(token) is None


def test_senha_errada_e_recuperacao(tmp_path):
    auth = AuthService(JsonAuthStore(str(tmp_path / "auth.json")))
    auth.register("Bia", "bia@empresa.com", "senha-forte")
    with pytest.raises(AuthError):
        auth.login("bia@empresa.com", "errada-123")

    _, code = auth.request_reset("bia@empresa.com")
    auth.reset_password("bia@empresa.com", code, "nova-senha-123")
    token, _ = auth.login("bia@empresa.com", "nova-senha-123")
    assert auth.user_for_token(token) is not None


def test_primeira_conta_vira_admin(tmp_path):
    store = JsonAuthStore(str(tmp_path / "auth.json"))
    auth = AuthService(store)
    first = auth.register("Ana", "ana@empresa.com", "senha-forte")
    auth.register("Bia", "bia@empresa.com", "senha-forte")
    auth.ensure_admin()
    assert store.user_by_id(first.id).is_admin
    assert sum(u.is_admin for u in store.list_users()) == 1
