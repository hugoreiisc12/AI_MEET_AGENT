"""Embeddings no próprio processo, em ONNX Runtime (ADR-022).

Não depende do sistema operacional nem do provider do LLM: o ONNX Runtime tem pacotes para Linux,
macOS e Windows (x86 e ARM) e roda igual dentro do Docker. Usa só o provedor de CPU, que existe em
todos eles. O modelo é baixado uma vez do Hugging Face para o cache (`HF_HOME`) na primeira chamada.

Padrão: `intfloat/multilingual-e5-small` (MIT, 100+ idiomas, treinado para busca, 384 dimensões),
arquivo `onnx/model.onnx` genérico (fp32). Modelos E5 pedem os prefixos "query: " e "passage: ".
"""
from __future__ import annotations

import os
import threading

import numpy as np

from domain.interfaces.embedder import EmbeddingError, IEmbedder

DEFAULT_MODEL = "intfloat/multilingual-e5-small"


def mean_pool_normalize(hidden: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Média dos vetores dos tokens reais (o padding não entra) e norma 1 por linha."""
    weights = mask[..., None].astype(hidden.dtype)
    summed = (hidden * weights).sum(axis=1)
    counts = np.clip(weights.sum(axis=1), 1e-9, None)
    pooled = summed / counts
    norms = np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None)
    return pooled / norms


class OnnxEmbedder(IEmbedder):
    def __init__(self, model_name: str = DEFAULT_MODEL, max_length: int = 512, batch_size: int = 16,
                 cache_dir: str | None = None) -> None:
        self.model_name = model_name
        self._max_length = max_length
        self._batch_size = batch_size
        self._cache_dir = cache_dir
        self._session = None
        self._tokenizer = None
        self._inputs: set[str] = set()
        self._lock = threading.Lock()
        e5 = "e5" in model_name.lower()
        self._query_prefix = "query: " if e5 else ""
        self._doc_prefix = "passage: " if e5 else ""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed([self._doc_prefix + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._embed([self._query_prefix + text])[0]

    def _load(self) -> None:
        with self._lock:
            if self._session is not None:
                return
            try:
                import onnxruntime as ort
                from huggingface_hub import hf_hub_download
                from tokenizers import Tokenizer

                model_path = hf_hub_download(self.model_name, "onnx/model.onnx", cache_dir=self._cache_dir)
                tokenizer_path = hf_hub_download(self.model_name, "tokenizer.json", cache_dir=self._cache_dir)
                tokenizer = Tokenizer.from_file(tokenizer_path)
                pad = next((t for t in ("<pad>", "[PAD]") if tokenizer.token_to_id(t) is not None), None)
                tokenizer.enable_truncation(max_length=self._max_length)
                tokenizer.enable_padding(pad_id=tokenizer.token_to_id(pad) if pad else 0, pad_token=pad or "[PAD]")
                options = ort.SessionOptions()
                options.intra_op_num_threads = min(4, os.cpu_count() or 1)
                session = ort.InferenceSession(model_path, sess_options=options, providers=["CPUExecutionProvider"])
            except Exception as exc:
                raise EmbeddingError(f"Não foi possível carregar o modelo de embeddings {self.model_name}: {exc}") from exc
            self._inputs = {i.name for i in session.get_inputs()}
            self._tokenizer, self._session = tokenizer, session

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self._load()
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            encodings = self._tokenizer.encode_batch(texts[start:start + self._batch_size])
            ids = np.array([e.ids for e in encodings], dtype=np.int64)
            mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self._inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            try:
                hidden = self._session.run(None, feed)[0]
            except Exception as exc:
                raise EmbeddingError(f"Falha ao gerar embeddings: {exc}") from exc
            vectors.extend(mean_pool_normalize(hidden, mask).tolist())
        return vectors
