"""Contrato v2 (ADR-022, S15-2): invariantes de que o código depende, para o texto não derivar
antes de ser ligado ao agente. O completo serve ao resumo; o compacto, ao chat."""
from pathlib import Path

import pytest

from infrastructure.llm.meeting_agent import load_contract
from use_cases.contract_checks import DECISION_STATUSES

ROOT = Path(__file__).resolve().parent.parent
FULL = ROOT / "SPEC_CONTRACT_V2.md"
CHAT = ROOT / "SPEC_CONTRACT_CHAT_V2.md"
CHAT_MAX_CHARS = 6500  # ~2,5 mil tokens: o chat do modelo piso não pode voltar a gastar o prompt com o contrato


@pytest.mark.parametrize("path", [FULL, CHAT])
def test_regras_que_o_codigo_usa(path):
    text = load_contract(str(path))
    for status in DECISION_STATUSES:
        assert status in text.lower(), f"{path.name}: falta o estado de decisão {status}"
    assert "Isso não foi mencionado" in text  # contract_checks.contradicts_itself
    assert "[hh:mm] Nome: texto" in text  # formato que contract_checks confere
    assert "[Título da reunião · dd/mm/aaaa · hh:mm] Nome: texto" in text
    assert "Perguntas para você" in text
    assert "MEETING-INTELLIGENCE-002" in text


def test_completo_mantem_numeracao_do_v1():
    v1 = (ROOT / "SPEC_CONTRACT.md").read_text(encoding="utf-8")
    v2 = FULL.read_text(encoding="utf-8")
    for n in range(1, 19):  # o código cita §4, §7, §14 e §16 pelo número
        heading = next(line for line in v1.splitlines() if line.startswith(f"{n}. ") and line.isupper())
        assert heading in v2, heading
    assert "19. CONVERSA COM O USUÁRIO" in v2 and "20. CITAÇÕES E ORIGEM DAS INFORMAÇÕES" in v2


def test_contrato_do_chat_cabe_no_orcamento():
    assert len(CHAT.read_text(encoding="utf-8")) <= CHAT_MAX_CHARS
