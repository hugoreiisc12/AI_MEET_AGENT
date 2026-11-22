"""Memória entre reuniões (§14): continuidade pelos resumos gravados e notas do usuário."""
from datetime import datetime

import pytest

from domain.entities.meeting import Decision, Meeting, MeetingStatus, Summary, Task
from domain.interfaces.llm_service import ChatReply
from infrastructure.json_meeting_repository import JsonMeetingRepository
from infrastructure.memory_store import JsonMemoryStore
from use_cases.chat_with_meeting import ChatWithMeetingInput, ChatWithMeetingUC
from use_cases.meeting_memory import build_memory


def meeting(mid, owner, day, decisions=(), tasks=(), overview=""):
    return Meeting(id=mid, title=f"Reunião {mid}", owner_id=owner, status=MeetingStatus.DONE,
                   started_at=datetime(2026, 11, day, 10), transcript_text="x",
                   summary=Summary(overview=overview, decisions=list(decisions), tasks=list(tasks)))


ANTIGA = meeting("a", "ana", 3, decisions=[Decision("Migração do banco para a nuvem adiada", status="proposta")],
                 tasks=[Task("Orçar a fila de mensagens", "Bruno", "dia 10"), Task("Feita", "Carla", done=True)])
DEPOIS = meeting("d", "ana", 20, decisions=[Decision("Migração do banco para a nuvem aprovada", status="aprovada")])
ATUAL = meeting("c", "ana", 12, overview="Integração de pedidos e migração do banco")


def test_continuidade_com_origem_ordem_e_estado():
    block = build_memory(ATUAL, [ANTIGA, DEPOIS], [], "A migração do banco foi aprovada?")
    assert '[REUNIÃO ANTERIOR: "Reunião a", 03/11/2026] decisão (proposta): Migração do banco' in block
    assert '[REUNIÃO POSTERIOR: "Reunião d", 20/11/2026] decisão (aprovada)' in block
    assert "tarefa aberta: Orçar a fila de mensagens — responsável: Bruno — prazo: dia 10" in block
    assert "Feita" not in block  # tarefa concluída não é pendência
    assert "Decisão de reunião anterior pode ter sido revista" in block


def test_sem_registro_relacionado_diz_isso_e_sem_reunioes_nao_diz_nada():
    outra = meeting("o", "ana", 1, decisions=[Decision("Trocar o fornecedor de café")])
    assert "Não há, nas outras reuniões" in build_memory(ATUAL, [outra], [], "Quem cuida da integração?")
    assert build_memory(ATUAL, [], [], "qualquer") == ""


@pytest.fixture
def env(tmp_path):
    repo = JsonMeetingRepository(str(tmp_path / "m"))
    for m in (ANTIGA, DEPOIS, ATUAL, meeting("x", "bia", 5, decisions=[Decision("Migração do banco cancelada")])):
        repo.save(m)
    return repo, JsonMemoryStore(str(tmp_path / "memories.json"))


class Spy:
    def __init__(self, reply=None):
        self.reply, self.context = reply, ""

    def chat(self, question, context, history, question_context="", **_):
        self.context = context + question_context
        return self.reply or "ok"


def test_chat_ve_so_as_reunioes_do_mesmo_dono(env):
    repo, store = env
    spy = Spy()
    ChatWithMeetingUC(spy, repository=repo, memory_store=store).execute(
        ChatWithMeetingInput(meeting=repo.find_by_id("c"), question="E a migração do banco?"))
    assert "Reunião a" in spy.context and "Reunião d" in spy.context
    assert "cancelada" not in spy.context  # reunião da Bia nunca entra na memória da Ana


def test_remember_guarda_nota_que_vale_nas_outras_reunioes(env):
    repo, store = env
    tool = {"name": "remember", "arguments": {"note": "Prefiro atas em tópicos curtos"}}
    out = ChatWithMeetingUC(Spy(ChatReply("", tool)), repository=repo, memory_store=store).execute(
        ChatWithMeetingInput(meeting=repo.find_by_id("c"), question="Lembre que prefiro atas em tópicos curtos"))
    assert out.action["type"] == "memory" and "Anotado" in out.answer
    assert [n["text"] for n in store.list("ana")] == ["Prefiro atas em tópicos curtos"] and store.list("bia") == []

    spy = Spy()
    ChatWithMeetingUC(spy, repository=repo, memory_store=store).execute(
        ChatWithMeetingInput(meeting=repo.find_by_id("a"), question="Gere a ata"))
    assert "Prefiro atas em tópicos curtos" in spy.context  # outra reunião, mesma pessoa

    note_id = store.list("ana")[0]["_id"]
    assert store.delete("bia", note_id) is False and store.delete("ana", note_id) is True
    assert store.list("ana") == []
