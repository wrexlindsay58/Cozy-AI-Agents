import logging
from langchain_core.language_models.chat_models import BaseChatModel
from src.config import (
    LLM_PROVIDER,
    XAI_API_KEY,
    GROK_FAST_MODEL,
    GROK_PRO_MODEL,
    OLLAMA_BASE_URL,
    OLLAMA_FAST_MODEL,
    OLLAMA_PRO_MODEL,
    LLM_FALLBACK_ENABLED,
)

logger = logging.getLogger(__name__)


def _build_grok(model_name: str) -> BaseChatModel:
    from langchain_xai import ChatXAI

    if not XAI_API_KEY:
        raise ValueError("XAI_API_KEY is required for Grok. Get one at https://console.x.ai")
    return ChatXAI(
        model=model_name,
        xai_api_key=XAI_API_KEY,
        temperature=0,
        max_retries=2,
    )


def _build_ollama(model_name: str) -> BaseChatModel:
    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=model_name,
        base_url=OLLAMA_BASE_URL,
        temperature=0,
    )


def get_model(tier: str = "fast") -> BaseChatModel:
    """Return a chat model for the given tier: 'fast' (triage) or 'pro' (reasoning).

    Provider priority (when LLM_PROVIDER=auto):
      1. Grok (xAI) if XAI_API_KEY is set
      2. Ollama (local open source) if OLLAMA_BASE_URL is reachable
    """
    grok_model = GROK_FAST_MODEL if tier == "fast" else GROK_PRO_MODEL
    ollama_model = OLLAMA_FAST_MODEL if tier == "fast" else OLLAMA_PRO_MODEL

    if LLM_PROVIDER == "xai":
        return _build_grok(grok_model)
    if LLM_PROVIDER == "ollama":
        return _build_ollama(ollama_model)

    # auto: prefer Grok, fall back to Ollama
    if XAI_API_KEY:
        return _build_grok(grok_model)
    logger.warning("XAI_API_KEY not set — falling back to Ollama")
    return _build_ollama(ollama_model)


def invoke_with_fallback(messages: list, tier: str = "fast"):
    """Invoke a model with optional fallback to Ollama if Grok fails."""
    primary = get_model(tier)
    try:
        return primary.invoke(messages)
    except Exception as e:
        if not LLM_FALLBACK_ENABLED or LLM_PROVIDER == "ollama":
            raise
        logger.warning(f"Primary LLM failed ({e}), falling back to Ollama")
        fallback = _build_ollama(
            OLLAMA_FAST_MODEL if tier == "fast" else OLLAMA_PRO_MODEL
        )
        return fallback.invoke(messages)
