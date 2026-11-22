"""Embeddings (ADR-022) sem baixar modelo: pooling, prefixos E5, lotes e escolha do provider.
O teste com o modelo real só roda com EMBEDDING_MODEL_TEST=1 (baixa ~470 MB)."""
import os
from types import SimpleNamespace

import numpy as np
import pytest

from infrastructure.embeddings import build_embedder
from infrastructure.embeddings.onnx_embedder import OnnxEmbedder, mean_pool_normalize


def test_pooling_ignora_padding_e_normaliza():
    hidden = np.array([[[1.0, 0.0], [3.0, 0.0], [100.0, 100.0]]])  # 3º token é padding
    mask = np.array([[1, 1, 0]])
    out = mean_pool_normalize(hidden, mask)
    assert np.allclose(out, [[1.0, 0.0]])  # média de (1,0) e (3,0) = (2,0) → normalizado


class FakeTokenizer:
    def __init__(self):
        self.seen = []

    def encode_batch(self, texts):
        self.seen.append(list(texts))
        return [SimpleNamespace(ids=[1, 2, 0], attention_mask=[1, 1, 0]) for _ in texts]


class FakeSession:
    def __init__(self):
        self.feeds = []

    def run(self, _outputs, feed):
        self.feeds.append(feed)
        batch = feed["input_ids"].shape[0]
        return [np.tile(np.array([[3.0, 4.0], [3.0, 4.0], [9.0, 9.0]]), (batch, 1, 1))]


def fake_embedder(model="intfloat/multilingual-e5-small", batch_size=2):
    e = OnnxEmbedder(model, batch_size=batch_size)
    e._tokenizer, e._session, e._inputs = FakeTokenizer(), FakeSession(), {"input_ids", "attention_mask", "token_type_ids"}
    return e


def test_prefixos_e5_lotes_e_token_type_ids():
    e = fake_embedder()
    docs = e.embed_documents(["a", "b", "c"])
    query = e.embed_query("pergunta")
    assert e._tokenizer.seen == [["passage: a", "passage: b"], ["passage: c"], ["query: pergunta"]]
    assert all("token_type_ids" in f for f in e._session.feeds)
    assert np.allclose(docs, [[0.6, 0.8]] * 3) and np.allclose(query, [0.6, 0.8])
    assert e.embed_documents([]) == []


def test_modelo_sem_prefixo_quando_nao_e_e5():
    e = fake_embedder(model="sentence-transformers/qualquer")
    e.embed_query("oi")
    assert e._tokenizer.seen == [["oi"]]


def test_fabrica_escolhe_pelo_env():
    base = dict(embedding_model="m", ollama_base_url="http://h:11434/v1", openai_api_key="k")
    assert type(build_embedder(SimpleNamespace(embedding_provider="onnx", **base))).__name__ == "OnnxEmbedder"
    ollama = build_embedder(SimpleNamespace(embedding_provider="ollama", **base))
    assert ollama._url == "http://h:11434/api/embed"
    assert type(build_embedder(SimpleNamespace(embedding_provider="openai", **base))).__name__ == "OpenAIEmbedder"
    with pytest.raises(ValueError):
        build_embedder(SimpleNamespace(embedding_provider="outro", **base))


@pytest.mark.skipif(os.environ.get("EMBEDDING_MODEL_TEST") != "1", reason="baixa o modelo real (~470 MB)")
def test_modelo_real_entende_parafrase_em_portugues():
    e = OnnxEmbedder()
    q = np.array(e.embed_query("Quem ficou responsável pelo calendário de fechamento?"))
    docs = np.array(e.embed_documents([
        "Carla, você fica responsável por enviar o calendário de fechamento até sexta-feira.",
        "Sobre migrar o banco de dados para a nuvem, acho que vale a pena estudar.",
    ]))
    scores = docs @ q
    assert scores[0] > scores[1], scores
    assert docs.shape == (2, 384) and np.allclose(np.linalg.norm(docs, axis=1), 1.0, atol=1e-4)
