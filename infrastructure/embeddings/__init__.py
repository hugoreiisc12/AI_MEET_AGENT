"""Escolha do embedder pelo .env (ADR-022). EMBEDDING_PROVIDER: onnx (padrão) | ollama | openai."""
from domain.interfaces.embedder import IEmbedder


def build_embedder(settings) -> IEmbedder:
    provider = settings.embedding_provider
    if provider == "ollama":
        from infrastructure.embeddings.remote import OllamaEmbedder
        return OllamaEmbedder(settings.embedding_model, settings.ollama_base_url)
    if provider == "openai":
        from infrastructure.embeddings.remote import OpenAIEmbedder
        return OpenAIEmbedder(settings.embedding_model, settings.openai_api_key)
    if provider != "onnx":
        raise ValueError(f"EMBEDDING_PROVIDER inválido: {provider} (use onnx, ollama ou openai)")
    from infrastructure.embeddings.onnx_embedder import OnnxEmbedder
    return OnnxEmbedder(settings.embedding_model)
