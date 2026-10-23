"""
Token usage tracking via LangChain callbacks.

Logs token usage and costs to SQLite for every LLM call.
"""

import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional

from langchain_core.callbacks import BaseCallbackHandler

from v2.shared.pricing import get_pricing, get_display_name


# SQL schema for token usage table
SCHEMA = """
CREATE TABLE IF NOT EXISTS token_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    datetime TEXT NOT NULL,
    model TEXT NOT NULL,
    model_display TEXT NOT NULL,
    stage TEXT NOT NULL,
    file_path TEXT NOT NULL,
    thread_id TEXT,
    input_tokens INTEGER NOT NULL,
    cached_input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER NOT NULL,
    total_tokens INTEGER GENERATED ALWAYS AS (input_tokens + output_tokens) STORED,
    input_price_per_mtok REAL NOT NULL,
    output_price_per_mtok REAL NOT NULL,
    cached_input_price_per_mtok REAL DEFAULT 0,
    input_cost_usd REAL NOT NULL,
    cached_cost_usd REAL DEFAULT 0,
    output_cost_usd REAL NOT NULL,
    total_cost_usd REAL NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_token_usage_datetime ON token_usage(datetime);
CREATE INDEX IF NOT EXISTS idx_token_usage_file ON token_usage(file_path);
CREATE INDEX IF NOT EXISTS idx_token_usage_stage ON token_usage(stage);
CREATE INDEX IF NOT EXISTS idx_token_usage_model ON token_usage(model);
CREATE INDEX IF NOT EXISTS idx_token_usage_thread ON token_usage(thread_id);
"""


class TokenUsageCallback(BaseCallbackHandler):
    """
    LangChain callback to track token usage and costs.

    Usage:
        callback = TokenUsageCallback(
            db_path="v2/checkpoints/token_usage.db",
            stage="extract",
            file_path="raw_receipts/ah/...",
            thread_id="ah_...",
        )
        llm.invoke(messages, config={"callbacks": [callback]})
    """

    def __init__(
        self,
        db_path: str,
        stage: str,
        file_path: str,
        thread_id: str = None,
    ):
        self.db_path = db_path
        self.stage = stage
        self.file_path = file_path
        self.thread_id = thread_id
        self.model: str = "unknown"
        self._ensure_db()

    def _ensure_db(self):
        """Create database and table if not exists."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.executescript(SCHEMA)
        conn.close()

    def on_llm_start(self, serialized, prompts, **kwargs):
        """Capture model name when LLM starts."""
        # Model name is in invocation_params
        invocation_params = kwargs.get("invocation_params", {})
        self.model = invocation_params.get("model", "unknown")

        # Also check serialized kwargs
        if self.model == "unknown" and serialized:
            self.model = serialized.get("kwargs", {}).get("model", "unknown")

    def on_llm_end(self, response, **kwargs):
        """Log token usage when LLM completes."""
        # Extract model name if not captured in on_llm_start
        if self.model == "unknown":
            self.model = self._extract_model(response)

        # Extract usage from response
        usage = self._extract_usage(response)

        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        cached_tokens = usage.get("prompt_tokens_cached", 0) or usage.get("cached_tokens", 0) or 0

        # Get pricing
        try:
            pricing = get_pricing(self.model)
            model_display = get_display_name(self.model)
        except ValueError as e:
            print(f"Warning: {e}")
            pricing = {
                "input_per_mtok_usd": 0,
                "cached_input_per_mtok_usd": 0,
                "output_per_mtok_usd": 0,
            }
            model_display = self.model

        # Calculate costs
        regular_input = max(0, input_tokens - cached_tokens)
        input_cost = (regular_input * pricing["input_per_mtok_usd"]) / 1_000_000
        cached_cost = (cached_tokens * pricing["cached_input_per_mtok_usd"]) / 1_000_000
        output_cost = (output_tokens * pricing["output_per_mtok_usd"]) / 1_000_000
        total_cost = input_cost + cached_cost + output_cost

        # Save to database
        self._save(
            input_tokens=input_tokens,
            cached_input_tokens=cached_tokens,
            output_tokens=output_tokens,
            model_display=model_display,
            pricing=pricing,
            input_cost=input_cost,
            cached_cost=cached_cost,
            output_cost=output_cost,
            total_cost=total_cost,
        )

    def _extract_model(self, response) -> str:
        """Extract model name from response."""
        # Try llm_output
        if hasattr(response, "llm_output") and response.llm_output:
            llm_output = response.llm_output
            if "model" in llm_output:
                return llm_output["model"]
            if "model_name" in llm_output:
                return llm_output["model_name"]

        # Try generations
        if hasattr(response, "generations") and response.generations:
            try:
                message = response.generations[0][0].message
                if hasattr(message, "response_metadata") and message.response_metadata:
                    meta = message.response_metadata
                    if "model" in meta:
                        return meta["model"]
                    if "model_name" in meta:
                        return meta["model_name"]
            except (IndexError, AttributeError):
                pass

        # Try direct response_metadata
        if hasattr(response, "response_metadata") and response.response_metadata:
            meta = response.response_metadata
            if "model" in meta:
                return meta["model"]
            if "model_name" in meta:
                return meta["model_name"]

        return "unknown"

    def _extract_usage(self, response) -> dict:
        """Extract token usage from LLM response.

        Handles multiple response formats:
        - LLMResult (from callbacks): response.llm_output['token_usage']
        - AIMessage: response.usage_metadata or response.response_metadata['token_usage']
        - ChatGeneration: generation.message.usage_metadata
        """
        # Handle LLMResult (what callbacks receive)
        if hasattr(response, "llm_output") and response.llm_output:
            llm_output = response.llm_output

            # Mistral format in llm_output
            if "token_usage" in llm_output:
                tu = llm_output["token_usage"]
                cached = 0
                if "prompt_tokens_details" in tu:
                    cached = tu["prompt_tokens_details"].get("cached_tokens", 0)
                return {
                    "prompt_tokens": tu.get("prompt_tokens", 0),
                    "completion_tokens": tu.get("completion_tokens", 0),
                    "total_tokens": tu.get("total_tokens", 0),
                    "prompt_tokens_cached": cached,
                }

            # OpenAI-style in llm_output
            if "usage" in llm_output:
                u = llm_output["usage"]
                return {
                    "prompt_tokens": u.get("prompt_tokens", 0),
                    "completion_tokens": u.get("completion_tokens", 0),
                    "total_tokens": u.get("total_tokens", 0),
                    "prompt_tokens_cached": u.get("prompt_tokens_cached", 0) or u.get("cached_tokens", 0),
                }

        # Handle generations (LLMResult.generations[0][0].message)
        if hasattr(response, "generations") and response.generations:
            try:
                message = response.generations[0][0].message

                # Try usage_metadata first (LangChain standard)
                if hasattr(message, "usage_metadata") and message.usage_metadata:
                    um = message.usage_metadata
                    cached = 0
                    if um.get("input_token_details"):
                        cached = um["input_token_details"].get("cache_read", 0)
                    return {
                        "prompt_tokens": um.get("input_tokens", 0),
                        "completion_tokens": um.get("output_tokens", 0),
                        "total_tokens": um.get("total_tokens", 0),
                        "prompt_tokens_cached": cached,
                    }

                # Try response_metadata (Mistral format)
                if hasattr(message, "response_metadata") and message.response_metadata:
                    meta = message.response_metadata
                    if "token_usage" in meta:
                        tu = meta["token_usage"]
                        cached = 0
                        if "prompt_tokens_details" in tu:
                            cached = tu["prompt_tokens_details"].get("cached_tokens", 0)
                        return {
                            "prompt_tokens": tu.get("prompt_tokens", 0),
                            "completion_tokens": tu.get("completion_tokens", 0),
                            "total_tokens": tu.get("total_tokens", 0),
                            "prompt_tokens_cached": cached,
                        }
                    if "usage" in meta:
                        u = meta["usage"]
                        return {
                            "prompt_tokens": u.get("prompt_tokens", 0),
                            "completion_tokens": u.get("completion_tokens", 0),
                            "total_tokens": u.get("total_tokens", 0),
                            "prompt_tokens_cached": u.get("prompt_tokens_cached", 0) or u.get("cached_tokens", 0),
                        }
            except (IndexError, AttributeError):
                pass

        # Handle direct AIMessage (not wrapped in LLMResult)
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            um = response.usage_metadata
            return {
                "prompt_tokens": um.get("input_tokens", 0),
                "completion_tokens": um.get("output_tokens", 0),
                "total_tokens": um.get("total_tokens", 0),
                "prompt_tokens_cached": um.get("input_token_details", {}).get("cache_read", 0) if um.get("input_token_details") else 0,
            }

        if hasattr(response, "response_metadata") and response.response_metadata:
            meta = response.response_metadata
            if "token_usage" in meta:
                tu = meta["token_usage"]
                cached = 0
                if "prompt_tokens_details" in tu:
                    cached = tu["prompt_tokens_details"].get("cached_tokens", 0)
                return {
                    "prompt_tokens": tu.get("prompt_tokens", 0),
                    "completion_tokens": tu.get("completion_tokens", 0),
                    "total_tokens": tu.get("total_tokens", 0),
                    "prompt_tokens_cached": cached,
                }
            if "usage" in meta:
                u = meta["usage"]
                return {
                    "prompt_tokens": u.get("prompt_tokens", 0),
                    "completion_tokens": u.get("completion_tokens", 0),
                    "total_tokens": u.get("total_tokens", 0),
                    "prompt_tokens_cached": u.get("prompt_tokens_cached", 0) or u.get("cached_tokens", 0),
                }

        return {}

    def _save(
        self,
        input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
        model_display: str,
        pricing: dict,
        input_cost: float,
        cached_cost: float,
        output_cost: float,
        total_cost: float,
    ):
        """Save token usage to database."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO token_usage
                (datetime, model, model_display, stage, file_path, thread_id,
                 input_tokens, cached_input_tokens, output_tokens,
                 input_price_per_mtok, output_price_per_mtok, cached_input_price_per_mtok,
                 input_cost_usd, cached_cost_usd, output_cost_usd, total_cost_usd)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now().isoformat(),
                    self.model,
                    model_display,
                    self.stage,
                    self.file_path,
                    self.thread_id,
                    input_tokens,
                    cached_input_tokens,
                    output_tokens,
                    pricing["input_per_mtok_usd"],
                    pricing["output_per_mtok_usd"],
                    pricing.get("cached_input_per_mtok_usd", 0),
                    round(input_cost, 8),
                    round(cached_cost, 8),
                    round(output_cost, 8),
                    round(total_cost, 8),
                ),
            )
            conn.commit()
        finally:
            conn.close()


class TokenTracker:
    """
    Factory for creating TokenUsageCallback instances.

    Usage:
        tracker = TokenTracker(db_path="v2/checkpoints/token_usage.db")
        callback = tracker.create_callback(
            stage="extract",
            file_path="raw_receipts/ah/...",
            thread_id="ah_...",
        )
        llm.invoke(messages, config={"callbacks": [callback]})
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_db()

    def _ensure_db(self):
        """Create database and table if not exists."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.executescript(SCHEMA)
        conn.close()

    def create_callback(
        self,
        stage: str,
        file_path: str,
        thread_id: str = None,
    ) -> TokenUsageCallback:
        """Create a callback for a specific LLM call."""
        return TokenUsageCallback(
            db_path=self.db_path,
            stage=stage,
            file_path=file_path,
            thread_id=thread_id,
        )
