"""Embeddings por serviço (ADR-022): Ollama ou OpenAI, pela mesma porta do ONNX local.
Opcionais: o padrão é o ONNX no processo, que não depende de serviço externo."""
from __future__ import annotations

import numpy as np
import requests

from domain.interfaces.embedder import EmbeddingError, IEmbedder


def _normalize(vectors: list[list[float]]) -> list[list[float]]:
    arr = np.asarray(vectors, dtype=np.float32)
    norms = np.clip(np.linalg.norm(arr, axis=1, keepdims=True), 1e-12, None)
    return (arr / norms).tolist()


class OllamaEmbedder(IEmbedder):
    def __init__(self, model_name: str, base_url: str) -> None:
        self.model_name = model_name
        self._url = base_url.rstrip("/").removesuffix("/v1") + "/api/embed"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            resp = requests.post(self._url, json={"model": self.model_name, "input": texts}, timeout=300)
            resp.raise_for_status()
            return _normalize(resp.json()["embeddings"])
        except Exception as exc:
            raise EmbeddingError(f"Ollama não gerou embeddings ({self.model_name}): {exc}") from exc

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class OpenAIEmbedder(IEmbedder):
    def __init__(self, model_name: str, api_key: str) -> None:
        self.model_name = model_name
        self._api_key = api_key
        self._client = None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            if self._client is None:
                from openai import OpenAI
                self._client = OpenAI(api_key=self._api_key)
            resp = self._client.embeddings.create(model=self.model_name, input=texts)
            return _normalize([d.embedding for d in sorted(resp.data, key=lambda d: d.index)])
        except Exception as exc:
            raise EmbeddingError(f"OpenAI não gerou embeddings ({self.model_name}): {exc}") from exc

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]
