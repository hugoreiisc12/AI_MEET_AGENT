"""Agente em LangGraph e regras do contrato (ADR-014), sem modelo de verdade."""
import json

import pytest

from domain.entities.meeting_type import MeetingType
from domain.interfaces.llm_service import LLMServiceError
from infrastructure.llm.meeting_agent import MeetingAgent, parse_summary
from use_cases.contract_checks import FALLBACK, check_answer, decision_status

CTX = """[00:00] Ana: Bom dia, o objetivo é integrar pedidos com o financeiro.
[01:45] Bruno: Sobre migrar o banco de dados para a nuvem, acho que vale a pena estudar.
[02:05] Ana: Vamos deixar a migração para a nuvem para discutir em outra reunião."""


class FakeModel:
    """Devolve as respostas em ordem e guarda as mensagens recebidas."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def complete(self, messages, as_json=False):
        self.calls.append(messages)
        return self.answers.pop(0)

    def complete_tools(self, messages, tools):
        """Resposta em texto; um dict na lista de respostas é um pedido de ferramenta."""
        answer = self.complete(messages)
        return (answer, None) if isinstance(answer, str) else ("", answer)


def agent(*answers):
    model = FakeModel(*answers)
    return MeetingAgent(model=model, contract="CONTRATO DE TESTE"), model


# ── Checagens do contrato ────────────────────────────────────────────

def test_resposta_fiel_passa():
    ok = 'Ana disse que o objetivo é integrar pedidos. Ela afirmou: "Vamos deixar a migração para a nuvem para discutir em outra reunião."'
    assert check_answer(ok, CTX, "O que foi dito?") == []


def test_citacao_inventada_e_fala_de_quem_nao_estava():
    assert any("citação" in v for v in check_answer('Ana disse: "a migração está aprovada para março"', CTX))
    assert any("Carlos" in v for v in check_answer("Segundo Carlos, o prazo é março.", CTX))
    assert check_answer("Ninguém disse quem fará a revisão.", CTX) == []


def test_linha_com_horario_ou_autor_trocado():
    certo = "- [01:45] Bruno: Sobre migrar o banco de dados para a nuvem, acho"
    trocado = "- [02:05] Bruno: Sobre migrar o banco de dados para a nuvem, acho"
    assert check_answer(certo, CTX) == []
    assert any("[02:05] Bruno" in v for v in check_answer(trocado, CTX))


def test_contradicao_e_idioma():
    assert any("não foi mencionado" in v for v in check_answer(
        "Isso não foi mencionado durante a reunião. Mas Ana disse que o objetivo é integrar pedidos.", CTX))
    assert check_answer("Isso não foi mencionado durante a reunião.", CTX) == []
    assert any("português" in v for v in check_answer("The meeting was about the integration and it was fine.", CTX, "Como foi?"))
    assert check_answer("The meeting was about integrating orders.", CTX, "What was the meeting about?") == []


def test_status_da_decisao_nunca_aprovada_por_omissao():
    assert decision_status("Aprovado") == "aprovada"
    assert decision_status("em discussão") == "proposta"
    assert decision_status("") == decision_status("talvez") == "inconclusiva"


# ── Grafo do chat ────────────────────────────────────────────────────

def test_chat_leva_o_contrato_e_o_contexto():
    a, model = agent("A reunião tratou da integração de pedidos com o financeiro.")
    assert a.chat("Do que tratou?", CTX, history=[{"role": "user", "content": "oi"}]).answer.startswith("A reunião")
    system = model.calls[0][0]["content"]
    assert system.startswith("CONTRATO DE TESTE") and CTX in system
    assert [m["role"] for m in model.calls[0]] == ["system", "user", "user"]


def test_chat_corrige_uma_vez_com_as_violacoes():
    a, model = agent('Segundo Carlos, "a migração está aprovada para março".', "A migração não foi aprovada.")
    assert a.chat("A migração foi aprovada?", CTX, history=[]).answer == "A migração não foi aprovada."
    correction = model.calls[1][-1]["content"]
    assert "violou o contrato" in correction and "Carlos" in correction


def test_chat_desiste_com_resposta_padrao():
    a, model = agent("Segundo Carlos, sim.", "Segundo Carlos, sim mesmo.")
    assert a.chat("Foi aprovada?", CTX, history=[]).answer == FALLBACK
    assert len(model.calls) == 2


# ── Grafo do resumo ──────────────────────────────────────────────────

SUMMARY = {"overview": "Integração", "topics": ["Financeiro"],
           "tasks": [{"description": "Revisar contratos", "responsible": "Carlos"},
                     {"description": "Enviar calendário", "responsible": "Ana", "deadline": "sexta"}],
           "decisions": [{"description": "Migrar para a nuvem", "status": "talvez"},
                         {"description": "Integrar antes do dia 25", "status": "aprovado"}]}


def test_resumo_aplica_o_contrato():
    a, model = agent(json.dumps(SUMMARY))
    s = a.summarize(CTX, MeetingType.PLANNING)
    assert [(t.description, t.responsible) for t in s.tasks] == [("Revisar contratos", "Não definido"),
                                                                  ("Enviar calendário", "Ana")]
    assert [d.status for d in s.decisions] == ["inconclusiva", "aprovada"]
    system = model.calls[0][0]["content"]
    assert system.startswith("CONTRATO DE TESTE") and "planejamento" in system.lower()


def test_resumo_refaz_json_invalido_e_desiste_na_segunda():
    a, model = agent("isto não é json", json.dumps(SUMMARY))
    assert a.summarize(CTX).overview == "Integração"
    assert "inválido" in model.calls[1][-1]["content"]
    with pytest.raises(LLMServiceError, match="JSON inválido"):
        agent("nada", "nada de novo")[0].summarize(CTX)


def test_json_com_chave_final_cortada():
    assert parse_summary('{"overview": "ok", "topics": [], "tasks": [], "decisions": []', "").overview == "ok"


def test_contrato_padrao_e_o_spec_do_repositorio():
    from infrastructure.llm.meeting_agent import load_contract
    assert "MEETING-INTELLIGENCE-001" in load_contract("SPEC_CONTRACT.md")
    with pytest.raises(LLMServiceError, match="não encontrado"):
        load_contract("nao-existe.md")


def test_chat_recebe_decisoes_classificadas_do_resumo():
    from domain.entities.meeting import Decision, Meeting, Summary
    from use_cases.chat_with_meeting import ChatWithMeetingInput, ChatWithMeetingUC
    a, model = agent("Só a integração foi aprovada.")
    m = Meeting(id="m", title="t", transcript_text=CTX, transcript_formatted=CTX,
                summary=Summary(decisions=[Decision("Migrar para a nuvem", status="proposta")]))
    ChatWithMeetingUC(a).execute(ChatWithMeetingInput(meeting=m, question="O que foi aprovado?", history=[]))
    assert "- [proposta] Migrar para a nuvem" in model.calls[0][0]["content"]


# ── Ferramentas ──────────────────────────────────────────────────────

def test_pedido_de_ferramenta_sai_no_reply_sem_texto():
    tool = {"name": "create_document", "arguments": {"format": "pdf", "title": "Ata",
            "content": "## Decisões\n- A integração entra em produção antes do dia 25."}}
    a, _ = agent(tool)
    reply = a.chat("Gere um PDF com as decisões", CTX, history=[])
    assert reply.tool == tool and reply.answer == ""


def test_conteudo_do_documento_passa_pela_verificacao():
    inventado = {"name": "create_document", "arguments": {"format": "pdf", "title": "Ata",
                 "content": 'Ana disse: "a migração está aprovada para março e sem custo"'}}
    corrigido = {"name": "create_document", "arguments": {"format": "pdf", "title": "Ata",
                 "content": "A migração para a nuvem ficou para outra reunião."}}
    a, model = agent(inventado, corrigido)
    assert a.chat("Gere um PDF", CTX, history=[]).tool == corrigido
    assert "citação" in model.calls[1][-1]["content"]  # a correção foi pedida com a violação


def test_titulo_entre_aspas_no_documento_nao_e_citacao():
    from infrastructure.llm.meeting_agent import _tool_text
    tool = {"name": "create_document", "arguments": {"title": "Tarefas da Reunião de Integração",
            "content": '# "Tarefas da Reunião de Integração"\n- Carla envia o calendário'}}
    assert check_answer(_tool_text(tool), CTX, "Gere um Word") == []
    inventada = {"name": "create_document", "arguments": {"title": "Ata",
                 "content": 'Ana disse: "a migração está aprovada para março e sem custo"'}}
    assert check_answer(_tool_text(inventada), CTX, "Gere") != []


def test_cabecalho_entre_aspas_com_titulo_da_reuniao_nao_e_citacao():
    from infrastructure.llm.meeting_agent import _tool_text
    tool = {"name": "create_document", "arguments": {"title": "Tarefas",
            "content": '# "Tarefas da Reunião de Integração Pedidos com Financeiro"\n'
                       '**"Reunião de Integração Pedidos com Financeiro"**\n- Carla envia o calendário'}}
    assert check_answer(_tool_text(tool), CTX, "Gere um Word") == []


def test_titulo_entre_aspas_no_meio_do_texto_nao_e_citacao_mas_fala_e():
    from infrastructure.llm.meeting_agent import _tool_text
    titulo = {"name": "create_document", "arguments": {"title": "Ata",
              "content": 'Este é o registro "Decisões e Discordâncias da Reunião de Integração" de hoje.'}}
    assert check_answer(_tool_text(titulo), CTX, "Gere") == []
    fala = {"name": "send_email", "arguments": {"subject": "x",
            "body": 'Na reunião, Ana disse: "a migração está aprovada para março e sem custo".'}}
    assert any("citação" in v for v in check_answer(_tool_text(fala), CTX, "Mande"))


def test_copiar_a_nota_do_sistema_sem_chamar_a_ferramenta_e_violacao():
    tool = {"name": "send_email", "arguments": {"to": ["a@b.com"], "subject": "Ata",
            "body": "A integração entra em produção antes do dia 25."}}
    a, model = agent("[O sistema executou a ferramenta send_email com anexo para o pedido acima.]", tool)
    assert a.chat("Mande a ata em PDF para a@b.com", CTX, history=[]).tool == tool
    assert "sem usar a ferramenta" in model.calls[1][-1]["content"]


def test_dizer_que_gerou_sem_usar_ferramenta_e_violacao():
    tool = {"name": "create_document", "arguments": {"format": "pdf", "title": "Ata",
            "content": "A integração entra em produção antes do dia 25."}}
    a, model = agent("Gerei o documento Ata em PDF. Baixe pelo botão abaixo.", tool)
    assert a.chat("Gere um PDF", CTX, history=[]).tool == tool
    assert "sem usar a ferramenta" in model.calls[1][-1]["content"]


def test_remember_so_quando_o_usuario_pede():
    note = {"name": "remember", "arguments": {"note": "Definir líder da migração"}}
    svc, model = agent(note, "Ficou em aberto quem lidera a migração.")
    reply = svc.chat("O que ficou em aberto nesta reunião?", context=CTX, history=[])
    assert reply.tool is None and "lidera" in reply.answer and len(model.calls) == 2
    svc, _ = agent(note)
    assert svc.chat("Lembre que prefiro atas curtas", context=CTX, history=[]).tool == note


def test_origem_da_fala_de_outra_reuniao_confere():
    ctx = ('REUNIÃO ABERTA (é sobre esta que o usuário pergunta): "Integração", 03/11/2026\n\n'
           "[00:01] Ana: integração antes do dia 25\n"
           "[Acompanhamento · 10/11/2026 · 01:40] Ana: Bruno, você fica com a revisão dos contratos da fila.")
    ok = "[Acompanhamento · 10/11/2026 · 01:40] Ana: Bruno, você fica com a revisão dos contratos da fila."
    assert check_answer(ok, ctx) == []
    wrong_meeting = "[Integração · 03/11/2026 · 01:40] Ana: Bruno, você fica com a revisão dos contratos da fila."
    assert any("não confere" in v for v in check_answer(wrong_meeting, ctx))
    prose = 'Na reunião "Integração", Ana disse: "Bruno, você fica com a revisão dos contratos da fila."'
    assert any("mas ela é de" in v for v in check_answer(prose, ctx))
    assert any("não está no contexto" in v for v in check_answer("Ver [Orçamento · 01/01/2026].", ctx))


def test_resumo_v2_grava_contribuicoes_mapa_e_questoes():
    raw = json.dumps({"overview": "o", "topics": ["fila"], "tasks": [], "decisions": [],
                      "contributions": [{"speaker": "Bruno", "points": ["propôs a fila"]},
                                        {"speaker": "Zé Inventado", "points": ["x"]}],
                      "topic_decisions": [{"topic": "fechamento", "decision": "integração antes do 25", "effect": "prazo"}],
                      "open_questions": ["Quem revisa os contratos?"]})
    s = parse_summary(raw, CTX)
    assert [c["speaker"] for c in s.contributions] == ["Bruno"]  # quem não está na reunião sai
    assert s.topic_decisions[0]["effect"] == "prazo" and s.open_questions == ["Quem revisa os contratos?"]
    assert "## Questões em aberto" in s.formatted and "fechamento → integração antes do 25 (prazo)" in s.formatted


def test_intencao_da_pergunta():
    from use_cases.chat_with_meeting import classify_intent
    assert classify_intent("O que ficou em aberto nesta reunião?") == "pendências"
    assert classify_intent("A data mudou em relação à reunião anterior?") == "entre reuniões"
    assert classify_intent("O que você achou da reunião?") == "análise"
    assert classify_intent("Quem fica com o calendário?") == "fato"


def test_data_inventada_reprova():
    assert any("data 05/12/2026" in v for v in check_answer("A entrega ficou para 05/12/2026.", CTX))


def test_reuniao_aberta_citada_pelo_titulo_vale():
    ctx = ('REUNIÃO ABERTA (é sobre esta que o usuário pergunta): "Acompanhamento", 10/11/2026\n\n'
           "[01:05] Ana: Então mudamos: a integração entra no dia 28.")
    assert check_answer("[Acompanhamento · 10/11/2026 · 01:05] Ana: Então mudamos: a integração entra no dia 28.", ctx) == []
    assert check_answer("[Acompanhamento · 10/11/2026 · 01:05] Bruno: Então mudamos: a integração entra no dia 28.", ctx)
