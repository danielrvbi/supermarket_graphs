"""
Mistral LLM client wrapper using LangChain.
"""

from functools import lru_cache
from typing import Optional

from langchain_mistralai import ChatMistralAI
from v2.common.settings import settings


@lru_cache(maxsize=4)
def get_mistral_llm(temperature: float = 0.0, model: Optional[str] = None) -> ChatMistralAI:
    """
    Get a configured Mistral LLM instance.

    Uses settings.MISTRAL_MODEL (mistral-small-latest) by default for cost efficiency.
    Cached to reuse the same instance per (temperature, model).

    Args:
        temperature: Sampling temperature (0 for deterministic)
        model: Mistral model name; None = settings.MISTRAL_MODEL

    Returns:
        Configured ChatMistralAI instance
    """
    if not settings.MISTRAL_KEY:
        raise ValueError(
            "MISTRAL_KEY not set. Please add it to your .env file.\n"
            "Get your key from: https://console.mistral.ai/"
        )

    return ChatMistralAI(
        model=model or settings.MISTRAL_MODEL,
        temperature=temperature,
        api_key=settings.MISTRAL_KEY,
        max_retries=3,
    )


def get_structured_llm(schema: type, temperature: float = 0.0) -> ChatMistralAI:
    """
    Get a Mistral LLM configured for structured output with a Pydantic schema.

    Args:
        schema: Pydantic model class for structured output
        temperature: Sampling temperature

    Returns:
        LLM with structured output binding
    """
    llm = get_mistral_llm(temperature=temperature)
    return llm.with_structured_output(schema)
