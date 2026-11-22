"""Porta de embeddings (ADR-022): texto → vetor, para a busca semântica da memória do agente.

Documentos (trechos de reunião) e perguntas são embutidos por métodos separados porque alguns
modelos (família E5) pedem prefixos diferentes para cada lado da busca. Os vetores saem
normalizados (norma 1): a similaridade de cosseno vira um produto interno.
"""
from abc import ABC, abstractmethod


class IEmbedder(ABC):
    """Contrato de qualquer provider de embeddings (ONNX local, Ollama, OpenAI)."""

    #: Identifica o espaço vetorial; vai gravado junto de cada vetor. Trocar de modelo = reindexar.
    model_name: str

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Vetores normalizados dos trechos a indexar, na mesma ordem da entrada."""
        ...

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Vetor normalizado de uma pergunta."""
        ...


class EmbeddingError(Exception):
    """Falha ao carregar o modelo ou ao gerar embeddings."""
