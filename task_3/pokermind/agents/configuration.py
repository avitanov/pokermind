"""Shared player model and three strategy-specific agent configurations."""

import os

from strands import Agent
from strands.models.openai import OpenAIModel
from strands.types.agent import Limits

from task_3.pokermind.agents.state import _STRATEGY_PROMPTS
from task_3.pokermind.agents.tools import get_opponent_statistics, peek_opponent_card
from task_3.pokermind.core.domain import PLAYER_MODEL_ID, PlayerName, PokerDecision

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
PLAYER_PROVIDER_ROUTING = {
    "only": ["cloudflare"],
    "allow_fallbacks": False,
}
OPENROUTER_TIMEOUT_SECONDS = 60.0
PLAYER_INVOCATION_LIMITS: Limits = {
    "turns": 4,
    "output_tokens": 2_000,
    "total_tokens": 12_000,
}
MAX_DECISION_ATTEMPTS = 6  # one call plus five retries
FALLBACK_REASON = "Deterministic fallback after agent failure."
API_FALLBACK_REASON = "Deterministic fold after API failure."
_LIMIT_STOP_REASONS = {
    "limit_turns",
    "limit_output_tokens",
    "limit_total_tokens",
}

_SHARED_PROMPT = """You are one player in a modified No-Limit Texas Hold'em tournament.
Return only ACTION, AMOUNT, and a concise observable REASON. FOLD and CHECK use
amount 0; CALL uses the exact legal amount; RAISE is chips added now. Obey the
listed legal actions exactly. Use only the supplied visible state and never
assume hidden cards or private reasoning."""


def create_player_model() -> OpenAIModel:
    """Create the fixed shared OpenRouter model used by all poker players."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required to create player agents.")
    return OpenAIModel(
        client_args={
            "api_key": api_key,
            "base_url": OPENROUTER_BASE_URL,
            "timeout": OPENROUTER_TIMEOUT_SECONDS,
            "max_retries": 0,
        },
        model_id=PLAYER_MODEL_ID,
        params={
            "temperature": 0.1,
            "max_tokens": PLAYER_INVOCATION_LIMITS["output_tokens"],
            "extra_body": {
                "reasoning": {"enabled": False, "exclude": True},
                "provider": PLAYER_PROVIDER_ROUTING,
            },
        },
    )


def create_player_agents(model: OpenAIModel | None = None) -> dict[PlayerName, Agent]:
    """Create exactly three strategy-specific agents sharing one model instance."""
    shared_model = model or create_player_model()
    return {
        player: Agent(
            model=shared_model,
            tools=[get_opponent_statistics, peek_opponent_card]
            if player is PlayerName.ADAPTIVE
            else [],
            system_prompt=f"{_SHARED_PROMPT}\n{strategy}",
            structured_output_model=PokerDecision,
            callback_handler=None,
            retry_strategy=None,
            name=f"{player.value} Agent",
        )
        for player, strategy in _STRATEGY_PROMPTS.items()
    }
