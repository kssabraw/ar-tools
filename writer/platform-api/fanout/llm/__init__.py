from functools import lru_cache

from .anthropic_client import AnthropicError, AnthropicLLM
from .openai_client import LLMError, OpenAILLM

__all__ = [
    "OpenAILLM",
    "LLMError",
    "AnthropicLLM",
    "AnthropicError",
    "get_llm",
    "get_orchestrator",
    "active_embedding_model",
]


def active_embedding_model() -> str:
    """The embedding model the app is currently configured to use. Source of truth
    for tagging new sessions (`sessions.embedding_model`) and the freeze-old-sessions
    guard, so vectors are never compared across the OpenAI/Gemini boundary."""
    from fanout.config import get_settings

    s = get_settings()
    if s.embedding_provider == "gemini":
        return s.gemini_embedding_model
    return s.openai_embedding_model


@lru_cache
def get_llm() -> OpenAILLM:
    from fanout.config import get_settings

    s = get_settings()
    # Embedding backend is a config switch (locked-decision override 2026-06-15:
    # OpenAI -> Gemini, whole-app). Default "openai" keeps the swap dormant until
    # GEMINI_API_KEY is provisioned + the cosine thresholds are recalibrated live.
    embedder = None
    if s.embedding_provider == "gemini":
        from .embeddings import GeminiEmbedder

        embedder = GeminiEmbedder(
            api_key=s.gemini_api_key,
            model=s.gemini_embedding_model,
            output_dim=s.gemini_embedding_dim,
            task_type=s.gemini_embedding_task_type,
            max_workers=s.gemini_embedding_max_workers,
        )
    return OpenAILLM(
        api_key=s.openai_api_key,
        silo_model=s.openai_silo_model,
        embedding_model=s.openai_embedding_model,
        web_search_tool=s.openai_web_search_tool,
        embedder=embedder,
    )


@lru_cache
def get_orchestrator() -> AnthropicLLM:
    from fanout.config import get_settings

    s = get_settings()
    return AnthropicLLM(
        api_key=s.anthropic_api_key,
        model=s.orchestrator_model,
        max_tokens=s.orchestrator_max_tokens,
        timeout_s=s.orchestrator_timeout_s,
    )
