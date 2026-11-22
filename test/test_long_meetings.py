"""Reuniões longas, histórico de chat e medições (ADR-010, Sprint 4)."""
from domain.entities.meeting import Meeting, Summary, Task
from infrastructure.json_meeting_repository import JsonMeetingRepository
from use_cases.chat_with_meeting import ChatWithMeetingInput, ChatWithMeetingUC
from use_cases.llm_context import select_relevant, split_by_lines
from use_cases.summarize_meeting import SummarizeMeetingInput, SummarizeMeetingUC


class FakeLLM:
    def __init__(self):
        self.summarized, self.chats = [], []

    def summarize(self, transcript, meeting_type=None):
        self.summarized.append(transcript)
        n = len(self.summarized)
        return Summary(overview=f"visão {n}", topics=["comum", f"tópico {n}"], tasks=[Task(f"tarefa {n}")])

    def chat(self, question, context, history, question_context="", **_):
        self.chats.append({"question": question, "context": context + question_context, "history": history})
        return "resposta"


def long_meeting(lines=200):
    text = "\n".join(f"[{i:03d}] Ana: fala número {i} sobre assunto{i}" for i in range(lines))
    return Meeting(id="m1", title="t", transcript_text=text, transcript_formatted=text, participants=["Ana", "Bruno"])


def test_split_respeita_o_limite_sem_cortar_linha():
    text = "\n".join(["a" * 40] * 10)
    parts = split_by_lines(text, 100)
    assert all(len(p) <= 100 for p in parts) and "\n".join(parts) == text
    assert split_by_lines("x" * 500, 100) == ["x" * 500]   # linha gigante não é cortada
    assert split_by_lines("", 100) == [""]


def test_resumo_de_reuniao_longa_e_feito_em_partes_e_reunido():
    llm, m = FakeLLM(), long_meeting()
    out = SummarizeMeetingUC(llm, max_context_chars=3000).execute(SummarizeMeetingInput(meeting=m))
    n = len(llm.summarized)
    assert out.success and n > 1 and m.metrics["llm_parts"] == n
    # toda parte cabe no limite e leva a lista de presentes
    assert all(p.startswith("PARTICIPANTES DA REUNIÃO: Ana, Bruno") and len(p) < 3200 for p in llm.summarized)
    assert out.summary.overview.split("\n\n") == [f"visão {i}" for i in range(1, n + 1)]
    assert out.summary.topics.count("comum") == 1 and len(out.summary.tasks) == n


def test_reuniao_curta_continua_num_pedido_so():
    llm, m = FakeLLM(), long_meeting(lines=5)
    SummarizeMeetingUC(llm).execute(SummarizeMeetingInput(meeting=m))
    assert len(llm.summarized) == 1 and "(Parte" not in llm.summarized[0]


def test_select_relevant_traz_o_trecho_da_pergunta_dentro_do_limite():
    text = long_meeting().transcript_text
    chosen = select_relevant(text, "o que foi dito sobre assunto150?", max_chars=1500, part_chars=500)
    assert "assunto150" in chosen and len(chosen) <= 1600


def test_chat_de_reuniao_longa_usa_resumo_e_trechos(tmp_path):
    llm, m = FakeLLM(), long_meeting()
    m.summary = Summary(overview="RESUMO-CURTO")
    ChatWithMeetingUC(llm, max_context_chars=3000).execute(ChatWithMeetingInput(meeting=m, question="e o assunto150?"))
    ctx = llm.chats[0]["context"]
    assert "RESUMO-CURTO" in ctx and "assunto150" in ctx and "Ana, Bruno" in ctx
    assert len(ctx) < 4500 and "assunto010" not in ctx


def test_chat_guarda_a_conversa_na_reuniao(tmp_path):
    repo = JsonMeetingRepository(str(tmp_path))
    llm, m = FakeLLM(), long_meeting(lines=3)
    repo.save(m)  # em produção a reunião sempre existe antes do chat
    uc = ChatWithMeetingUC(llm, repository=repo)
    uc.execute(ChatWithMeetingInput(meeting=m, question="primeira?"))
    uc.execute(ChatWithMeetingInput(meeting=repo.find_by_id("m1"), question="segunda?"))
    saved = repo.find_by_id("m1")
    assert [h["content"] for h in saved.chat_history] == ["primeira?", "resposta", "segunda?", "resposta"]
    # a segunda pergunta foi ao LLM com a primeira troca como histórico
    assert [h["content"] for h in llm.chats[1]["history"]] == ["primeira?", "resposta"]


def test_tarefa_concluida_e_medicoes_sobrevivem_a_ida_e_volta(tmp_path):
    repo = JsonMeetingRepository(str(tmp_path))
    m = long_meeting(lines=2)
    m.summary = Summary(tasks=[Task("a"), Task("b", done=True)])
    m.metrics = {"transcribe_s": 1.5}
    repo.save(m)
    back = repo.find_by_id("m1")
    assert [t.done for t in back.summary.tasks] == [False, True] and back.metrics == {"transcribe_s": 1.5}


def test_ollama_usa_sempre_a_mesma_janela(monkeypatch):
    from types import SimpleNamespace
    from infrastructure.llm.meeting_agent import MeetingAgent
    from infrastructure.llm.model_client import ModelClient
    sent = []

    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"message": {"content": "ok"}}

    import requests
    monkeypatch.setattr(requests, "post", lambda url, json, timeout: sent.append(json) or Resp())
    cfg = SimpleNamespace(llm_provider="ollama", openai_api_key="", ollama_num_ctx_max=32768,
                          ollama_model="m", ollama_base_url="http://h:11434/v1", ollama_keep_alive="30m")
    svc = MeetingAgent(model=ModelClient(cfg), contract="")
    assert svc.chat("oi?", context="x" * 30000, history=[{"role": "user", "content": "antes"}]).answer == "ok"
    # Pedido grande e pequeno com a mesma janela: trocar de janela faz o Ollama recarregar (ADR-021).
    assert sent[0]["options"]["num_ctx"] == 32768 and "format" not in sent[0] and sent[0]["keep_alive"] == "30m"
    assert [m["role"] for m in sent[0]["messages"]] == ["system", "user", "user"]
    svc.chat("oi?", context="curto", history=[])
    assert sent[1]["options"]["num_ctx"] == 32768

    import pytest
    from domain.interfaces.llm_service import LLMServiceError
    with pytest.raises(LLMServiceError, match="excede"):
        svc.chat("oi?", context="x" * 200000, history=[])
