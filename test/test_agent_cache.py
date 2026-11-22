"""RAG entre reuniões, search_meetings e CAG (ADR-022, Sprint 14)."""
from datetime import datetime

import pytest

from domain.entities.meeting import Meeting, Summary, Task
from domain.interfaces.llm_service import ChatReply
from infrastructure.hot_cache import ProcessCache
from infrastructure.index_store import IndexStore
from infrastructure.json_meeting_repository import JsonMeetingRepository
from infrastructure.memory_store import JsonMemoryStore
from test_meeting_index import FakeEmbedder
from use_cases.agent_cache import AgentCache, InvalidatingMemory, InvalidatingRepository
from use_cases.chat_with_meeting import ChatWithMeetingInput, ChatWithMeetingUC
from use_cases.contract_checks import FALLBACK
from use_cases.meeting_index import MemoryIndexer
from use_cases.meeting_memory import new_note


class LLM:
    """Responde em ordem; um dict é um pedido de ferramenta. Guarda o que recebeu."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def chat(self, question, context, history, question_context="", **kw):
        self.calls.append({"question_context": question_context, **kw})
        reply = self.replies.pop(0) if self.replies else "Resposta."
        return ChatReply("", reply) if isinstance(reply, dict) else ChatReply(reply)


def meeting(mid, owner, text, title="", day=1, **kw):
    return Meeting(id=mid, owner_id=owner, title=title or mid, transcript_text=text, transcript_formatted=text,
                   started_at=datetime(2026, 11, day, 10), **kw)


@pytest.fixture
def env(tmp_path):
    cache = AgentCache(ProcessCache())
    repo = InvalidatingRepository(JsonMeetingRepository(str(tmp_path / "meetings")), cache)
    memory = InvalidatingMemory(JsonMemoryStore(str(tmp_path / "memories.json")), cache)
    indexer = MemoryIndexer(IndexStore(str(tmp_path / "index")), FakeEmbedder())
    paths = []

    def uc(llm):
        return ChatWithMeetingUC(llm, repository=repo, memory_store=memory, indexer=indexer, agent_cache=cache,
                                 metrics=lambda path, s: paths.append(path))
    return repo, memory, indexer, uc, paths


def ask(uc, repo, mid, question):
    return uc.execute(ChatWithMeetingInput(meeting=repo.find_by_id(mid), question=question, history=[]))


def test_pergunta_repetida_volta_do_cache_e_dado_novo_invalida(env):
    repo, memory, _, uc, paths = env
    repo.save(meeting("m1", "ana", "[00:01] Ana: a entrega é sexta"))
    llm = LLM("Ana disse que a entrega é sexta.", "Ana disse que a entrega é sexta.")
    chat = uc(llm)
    assert ask(chat, repo, "m1", "Quando é a entrega?").path in ("quente", "banco")
    again = ask(chat, repo, "m1", "  quando é a ENTREGA ")  # mesma pergunta, outra grafia
    assert again.path == "cache" and again.answer == "Ana disse que a entrega é sexta." and len(llm.calls) == 1
    assert [m["content"] for m in repo.find_by_id("m1").chat_history][-2:] == ["  quando é a ENTREGA ", again.answer]

    repo.save(meeting("m2", "ana", "[00:01] Ana: outra reunião"))  # reunião nova do dono
    assert ask(chat, repo, "m1", "Quando é a entrega?").path != "cache" and len(llm.calls) == 2
    memory.add(new_note("ana", "prefiro respostas curtas"))  # nota nova também muda a resposta
    assert ask(chat, repo, "m1", "Quando é a entrega?").path != "cache"
    assert paths[:2] == [paths[0], "cache"]


def test_acao_e_resposta_padrao_nao_entram_no_cache(env):
    repo, _, _, uc, _ = env
    repo.save(meeting("m1", "ana", "[00:01] Ana: oi"))
    llm = LLM(FALLBACK, FALLBACK)
    chat = uc(llm)
    ask(chat, repo, "m1", "Algo?")
    ask(chat, repo, "m1", "Algo?")
    assert len(llm.calls) == 2


def test_isolamento_do_cache_por_dono(env):
    """S14-5: mesma reunião (id), mesma pergunta, outro dono: nunca a resposta do primeiro."""
    repo, _, _, uc, _ = env
    repo.save(meeting("m1", "ana", "[00:01] Ana: o bônus é 10 mil"))
    chat = uc(LLM("O bônus é 10 mil.", "Não foi mencionado."))
    ask(chat, repo, "m1", "Qual o bônus?")
    bia = meeting("m1", "bia", "[00:01] Bia: pauta")
    out = chat.execute(ChatWithMeetingInput(meeting=bia, question="Qual o bônus?", history=[]))
    assert out.path != "cache" and "10 mil" not in out.answer


def test_falas_de_outras_reunioes_com_citacao_e_so_do_dono(env):
    repo, _, indexer, uc, _ = env
    repo.save(meeting("m1", "ana", "[00:01] Ana: integração antes do dia 25", title="Integração", day=3))
    later = meeting("m2", "ana", "[01:40] Ana: Bruno, você revisa os contratos da fila", title="Acompanhamento", day=10,
                    summary=Summary(topics=["contratos da fila"], tasks=[Task("revisar contratos", "Bruno")]))
    repo.save(later)
    repo.save(meeting("x9", "bia", "[00:05] Bia: os contratos da fila são sigilosos", title="Da Bia", day=11))
    llm = LLM()
    ask(uc(llm), repo, "m1", "Quem revisa os contratos da fila?")
    sent = llm.calls[0]["question_context"]
    assert "[Acompanhamento · 10/11/2026 · 01:40] Ana: Bruno, você revisa os contratos da fila" in sent
    assert "sigilosos" not in sent and "Da Bia" not in sent
    assert llm.calls[0]["can_search"] is True


def test_search_meetings_aprofunda_e_responde_com_o_que_voltou(env):
    repo, _, _, uc, _ = env
    repo.save(meeting("m1", "ana", "[00:01] Ana: pauta curta"))
    repo.save(meeting("m2", "ana", "[00:15] Bruno: a infraestrutura validou a fila", title="Acompanhamento", day=10))
    llm = LLM({"name": "search_meetings", "arguments": {"query": "infraestrutura fila"}},
              "[Acompanhamento · 10/11/2026 · 00:15] Bruno: a infraestrutura validou a fila")
    out = ask(uc(llm), repo, "m1", "O que o Bruno disse sobre a infraestrutura antes?")
    assert out.searched and out.answer.startswith("[Acompanhamento")
    second = llm.calls[1]
    assert "RESULTADO DA BUSCA" in second["question_context"] and "validou a fila" in second["question_context"]
    assert "can_search" not in second  # não deixa buscar de novo em laço


def test_camada_quente_evita_o_disco_e_percebe_reindexacao(tmp_path):
    store = IndexStore(str(tmp_path))
    indexer = MemoryIndexer(store, FakeEmbedder())
    m = meeting("m1", "ana", "[00:01] Ana: oi")
    indexer.chunks.ensure(m)
    other_process = IndexStore(str(tmp_path))  # API lendo o que o worker gravou
    other_process.load_chunks("m1")
    other_process.load_chunks("m1")
    assert other_process.disk_loads == 1
    import os
    path = tmp_path / "m1.npz"
    os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 10**9))  # outro processo reindexou
    other_process.load_chunks("m1")
    assert other_process.disk_loads == 2


def test_entidade_liga_reunioes_pelo_nome_da_pessoa(env):
    _, _, indexer, _, _ = env
    a = meeting("m1", "ana", "x", participants=["Bruno Lima"], summary=Summary(topics=["orçamento"]))
    b = meeting("m2", "ana", "x", participants=["Carla"], summary=Summary(topics=["férias"]))
    indexer.entities.link(a)
    indexer.entities.link(b)
    assert indexer.entities.related_meetings(b, "o que o bruno lima falou?") == {"m1"}


def test_painel_resume_caminhos_e_acerto():
    from api.routers.observability import _agent_memory
    counters = {"chat_answers_total|path=cache": 1, "chat_answers_total|path=quente": 3}
    lat = {"chat_seconds|path=cache": {"count": 1, "p50": 0.01, "p95": 0.01, "max": 0.01}}
    out = _agent_memory(counters, lat)
    assert out["cache_hit_rate"] == 0.25 and list(out["latency_by_path"]) == ["cache"]
