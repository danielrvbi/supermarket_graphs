"""
Model pricing and name mapping for cost tracking.

Maps Mistral API model names to display names and pricing tiers.
"""

# Pricing data (USD per million tokens)
PRICING = [
    {
        "model": "Z.ai GLM 5.3 Flash",
        "input_per_mtok_usd": 0.15,
        "cached_input_per_mtok_usd": 0.03,
        "output_per_mtok_usd": 0.5,
    },
    {
        "model": "Z.ai GLM 5.3",
        "input_per_mtok_usd": 1.4,
        "cached_input_per_mtok_usd": 0.14,
        "output_per_mtok_usd": 4.4,
    },
    {
        "model": "Mistral Medium 3.5",
        "input_per_mtok_usd": 1.5,
        "cached_input_per_mtok_usd": 0.15,
        "output_per_mtok_usd": 7.5,
    },
    {
        "model": "Mistral Small 4",
        "input_per_mtok_usd": 0.15,
        "cached_input_per_mtok_usd": 0.015,
        "output_per_mtok_usd": 0.6,
    },
    {
        "model": "Mistral Large 4",
        "input_per_mtok_usd": 1.36,
        "cached_input_per_mtok_usd": 0.14,
        "output_per_mtok_usd": 4.18,
    },
    {
        "model": "Mistral Large 3",
        "input_per_mtok_usd": 0.5,
        "cached_input_per_mtok_usd": 0.05,
        "output_per_mtok_usd": 1.5,
    },
    {
        "model": "Ministral 3 14B",
        "input_per_mtok_usd": 0.2,
        "cached_input_per_mtok_usd": 0.02,
        "output_per_mtok_usd": 0.2,
    },
    {
        "model": "Ministral 3 8B",
        "input_per_mtok_usd": 0.15,
        "cached_input_per_mtok_usd": 0.015,
        "output_per_mtok_usd": 0.15,
    },
    {
        "model": "Ministral 3 3B",
        "input_per_mtok_usd": 0.1,
        "cached_input_per_mtok_usd": 0.01,
        "output_per_mtok_usd": 0.1,
    },
]

# Map Mistral API model names to display names in PRICING
MODEL_NAME_MAP = {
    # Mistral Small variants
    "mistral-small-latest": "Mistral Small 4",
    "mistral-small-2501": "Mistral Small 4",
    "mistral-small": "Mistral Small 4",
    # Mistral Medium variants
    "mistral-medium-latest": "Mistral Medium 3.5",
    "mistral-medium-2508": "Mistral Medium 3.5",
    "mistral-medium": "Mistral Medium 3.5",
    # Mistral Large variants
    "mistral-large-latest": "Mistral Large 4",
    "mistral-large-2411": "Mistral Large 4",
    "mistral-large": "Mistral Large 4",
    # Ministral variants
    "ministral-8b-latest": "Ministral 3 8B",
    "ministral-8b-2410": "Ministral 3 8B",
    "ministral-3b-latest": "Ministral 3 3B",
    "ministral-3b-2410": "Ministral 3 3B",
    "ministral-14b-latest": "Ministral 3 14B",
    # Pixtral (vision)
    "pixtral-large-latest": "Mistral Large 4",  # Approximate pricing
    # Codestral
    "codestral-latest": "Mistral Large 4",  # Approximate pricing
}


def get_display_name(api_model: str) -> str:
    """Get display name for an API model name."""
    return MODEL_NAME_MAP.get(api_model, api_model)


def get_pricing(api_model: str) -> dict:
    """
    Get pricing for an API model name.

    Args:
        api_model: Mistral API model name (e.g., "mistral-small-latest")

    Returns:
        Pricing dict with input_per_mtok_usd, cached_input_per_mtok_usd, output_per_mtok_usd

    Raises:
        ValueError: If no pricing found for the model
    """
    display_name = get_display_name(api_model)

    for p in PRICING:
        if p["model"] == display_name:
            return p

    raise ValueError(
        f"No pricing found for model: {api_model} -> {display_name}. "
        f"Available models: {[p['model'] for p in PRICING]}"
    )


def calculate_cost(
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
    api_model: str = "mistral-small-latest",
) -> dict:
    """
    Calculate cost for a token usage.

    Args:
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        cached_input_tokens: Number of cached input tokens (billed at cached rate)
        api_model: API model name

    Returns:
        Dict with input_cost_usd, output_cost_usd, cached_cost_usd, total_cost_usd
    """
    pricing = get_pricing(api_model)

    # Cached tokens are billed at cached rate, regular input at full rate
    regular_input = max(0, input_tokens - cached_input_tokens)

    input_cost = (regular_input * pricing["input_per_mtok_usd"]) / 1_000_000
    cached_cost = (cached_input_tokens * pricing["cached_input_per_mtok_usd"]) / 1_000_000
    output_cost = (output_tokens * pricing["output_per_mtok_usd"]) / 1_000_000

    return {
        "input_cost_usd": round(input_cost, 8),
        "cached_cost_usd": round(cached_cost, 8),
        "output_cost_usd": round(output_cost, 8),
        "total_cost_usd": round(input_cost + cached_cost + output_cost, 8),
        "model": api_model,
        "model_display": get_display_name(api_model),
    }
