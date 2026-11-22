"""Memória longa e curta do agente (ADR-022, Sprint 13), com um embedder falso que conhece sinônimos."""
import os
import zlib
from types import SimpleNamespace

import numpy as np
import pytest

from domain.entities.meeting import Decision, Meeting, Summary, Task
from infrastructure.index_store import IndexStore
from infrastructure.llm.meeting_agent import MeetingAgent, conversation_digest
from use_cases.chat_with_meeting import ChatWithMeetingInput, ChatWithMeetingUC
from use_cases.llm_context import _words
from use_cases.meeting_index import MemoryIndexer, chunk_transcript

SYNONYMS = {"custa": "preco", "cobra": "preco", "valor": "preco", "mensalmente": "mes", "mes": "mes",
            "mensageria": "fila", "fila": "fila", "nuvem": "cloud", "cloud": "cloud"}


class FakeEmbedder:
    model_name = "fake"

    def __init__(self):
        self.calls = 0

    def _vec(self, text):
        v = np.zeros(64)
        for w in _words(text) | set(text.lower().split()):
            v[zlib.crc32(SYNONYMS.get(w, w).encode()) % 64] += 1
        return (v / (np.linalg.norm(v) or 1)).tolist()

    def embed_documents(self, texts):
        self.calls += 1
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


def indexer(tmp_path):
    return MemoryIndexer(IndexStore(str(tmp_path / "index")), FakeEmbedder())


def meeting(mid="m1", owner="ana", text="", **kw):
    return Meeting(id=mid, owner_id=owner, title=mid, transcript_text=text, transcript_formatted=text, **kw)


def test_trechos_por_fala_com_horario_oradores_e_sobreposicao():
    text = "\n".join(f"[00:{i:02d}] {'Ana' if i % 2 else 'Bruno'}: fala {i} " + "x" * 150 for i in range(8))
    chunks = chunk_transcript(text, max_chars=500)
    assert all(len(c["text"]) <= 500 for c in chunks) and len(chunks) > 2
    assert chunks[0]["start"] == "00:00" and chunks[0]["speakers"] == ["Bruno", "Ana"]
    assert chunks[0]["text"].splitlines()[-1] == chunks[1]["text"].splitlines()[0]  # uma fala de sobreposição
    assert all(line in "\n".join(c["text"] for c in chunks) for line in text.splitlines())


def test_indice_reaproveitado_e_refeito_quando_a_transcricao_muda(tmp_path):
    idx = indexer(tmp_path)
    m = meeting(text="[00:01] Ana: oi")
    idx.chunks.ensure(m)
    idx.chunks.ensure(m)
    assert idx.chunks._embedder.calls == 1
    m.transcript_formatted = "[00:01] Ana Souza: oi"  # nomes trocados depois
    assert "Ana Souza" in idx.chunks.ensure(m)[0][0]["text"]


def test_busca_hibrida_acha_parafrase_que_a_palavra_nao_acha(tmp_path):
    lines = [f"[{i // 60:02d}:{i % 60:02d}] Bruno: atualização número {i} sobre o cronograma do projeto" for i in range(300)]
    lines[150] = "[02:30] Carla: o fornecedor da fila cobra 12 mil por mes"
    m = meeting(text="\n".join(lines))
    found = indexer(tmp_path).chunks.search(m, "Quanto custa mensalmente a mensageria?", max_chars=700)
    assert "12 mil" in found and len(found) <= 800


def test_entidades_ligam_pessoa_e_topico_entre_reunioes(tmp_path):
    idx = indexer(tmp_path)
    first = meeting("m1", participants=["Ana", "Bruno"], summary=Summary(
        topics=["migração para a nuvem"], decisions=[Decision("migrar para a nuvem", status="proposta")],
        tasks=[Task("estimar o custo da nuvem", "Bruno")]))
    second = meeting("m2", participants=["Ana Souza", "Bruno Lima"], summary=Summary(
        topics=["migração para a cloud"], tasks=[Task("revisar contrato", "Bruno")]))
    idx.entities.link(first)
    data = idx.entities.link(second)
    people = [e for e in data["entities"] if e["kind"] == "pessoa"]
    topics = [e for e in data["entities"] if e["kind"] == "tópico"]
    assert sorted(e["name"] for e in people) == ["Ana Souza", "Bruno Lima"]  # primeiro nome ligou ao completo
    assert len(topics) == 1 and {m["meeting_id"] for m in data["mentions"] if m["entity"] == topics[0]["id"]} == {"m1", "m2"}
    assert len(idx.entities.link(second)["mentions"]) == len(data["mentions"])  # refazer não duplica
    third = meeting("m3", participants=["Ana Lima"], summary=Summary())
    assert len([e for e in idx.entities.link(third)["entities"] if e["kind"] == "pessoa"]) == 3  # outra Ana


def test_reuniao_apagada_sai_do_indice(tmp_path):
    idx = indexer(tmp_path)
    m = meeting(text="[00:01] Ana: segredo", participants=["Ana"], summary=Summary(topics=["segredo"]))
    idx.index(m)
    idx.forget(m)
    assert idx.store.load_chunks("m1") is None and idx.store.load_entities("ana") == {"entities": [], "mentions": []}


def test_isolamento_o_indice_nunca_devolve_trecho_de_outro_dono(tmp_path):
    """S13-5: mesmo com o mesmo id de reunião, o trecho da Ana não aparece para a Bia."""
    idx = indexer(tmp_path)
    idx.index(meeting("m1", "ana", "[00:01] Ana: o salário do diretor é 90 mil", participants=["Ana"],
                      summary=Summary(topics=["salário"])))
    found = idx.chunks.search(meeting("m1", "bia", "[00:01] Bia: pauta da semana"), "salário do diretor", 2000)
    assert "90 mil" not in found and "pauta" in found
    assert idx.store.load_entities("bia") == {"entities": [], "mentions": []}


class BrokenIndexer:
    store = SimpleNamespace(disk_loads=0)

    class chunks:
        @staticmethod
        def search(*_):
            raise RuntimeError("modelo indisponível")


class SpyLLM:
    def __init__(self):
        self.seen = ""

    def chat(self, question, context, history, question_context="", **_):
        self.seen = question_context
        return "ok"


def test_chat_cai_na_busca_por_palavra_se_o_indice_falhar():
    text = "\n".join(f"[00:{i % 60:02d}] Ana: assunto{i} " + "y" * 100 for i in range(400))
    llm = SpyLLM()
    ChatWithMeetingUC(llm, max_context_chars=3000, indexer=BrokenIndexer()).execute(
        ChatWithMeetingInput(meeting=meeting(text=text), question="e o assunto150?"))
    assert "assunto150" in llm.seen


def test_memoria_curta_quarenta_perguntas_sem_estourar_nem_esquecer():
    class Model:
        profile = SimpleNamespace(context_tokens=9000)
        calls = []

        def complete_tools(self, messages, tools):
            self.calls.append(messages)
            return "Resposta.", None
    model = Model()
    agent = MeetingAgent(model=model, contract="CONTRATO")
    history = [{"role": "user", "content": "Combinado: chame a Carla de gerente financeira."},
               {"role": "assistant", "content": "Certo, vou chamá-la assim. " + "z" * 900}]
    for n in range(39):
        history += [{"role": "user", "content": f"pergunta {n}?"}, {"role": "assistant", "content": "w" * 1200}]
    agent.chat("e agora?", context="[00:01] Carla: ok", history=history)
    sent = model.calls[-1]
    assert "gerente financeira" in sent[1]["content"] and sent[1]["content"].startswith("RESUMO DO INÍCIO")
    assert sum(len(m["content"]) for m in sent) <= (9000 - 2000) * 2.4  # cabe na janela
    assert sent[-1]["content"] == "e agora?" and sent[-2]["content"] == "w" * 1200  # o recente vai inteiro


def test_resumo_da_conversa_guarda_o_usuario_e_a_primeira_frase():
    digest = conversation_digest([{"role": "user", "content": "Prefiro respostas curtas."},
                                  {"role": "assistant", "content": "Entendido. Vou ser breve sempre."}])
    assert "Usuário: Prefiro respostas curtas." in digest and "Agente: Entendido." in digest
    assert "breve" not in digest


@pytest.mark.skipif(os.environ.get("EMBEDDING_MODEL_TEST") != "1", reason="baixa o modelo real (~470 MB)")
def test_modelo_real_acha_parafrase_em_reuniao_de_duas_horas(tmp_path):
    from infrastructure.embeddings.onnx_embedder import OnnxEmbedder
    from scripts.eval_agent import long_transcript
    text, _ = long_transcript()
    idx = MemoryIndexer(IndexStore(str(tmp_path)), OnnxEmbedder())
    found = idx.chunks.search(meeting(text=text), "Quanto custa por mês o serviço de mensageria?", 8000)
    assert "12 mil" in found
