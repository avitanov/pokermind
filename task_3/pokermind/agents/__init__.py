"""Public player-agent API."""

from task_3.pokermind.agents.configuration import (
    MAX_DECISION_ATTEMPTS,
    OPENROUTER_BASE_URL,
    OPENROUTER_TIMEOUT_SECONDS,
    PLAYER_INVOCATION_LIMITS,
    PLAYER_PROVIDER_ROUTING,
    create_player_agents,
    create_player_model,
)
from task_3.pokermind.agents.coordinator import coordinate_decision
from task_3.pokermind.agents.dispatch import invoke_player_once
from task_3.pokermind.agents.schemas import (
    DecisionAttemptRecord,
    DecisionOutcome,
    InvocationResponse,
    PlayerProviderStreamError,
    PokerDecisionValidationError,
    StructuredDecisionError,
)
from task_3.pokermind.agents.state import (
    build_visible_state,
    strategy_prompt_summary,
)
from task_3.pokermind.agents.tools import (
    MAX_TOOL_CALLS_PER_ATTEMPT,
    get_opponent_statistics,
    peek_opponent_card,
)
from task_3.pokermind.agents.validation import (
    build_correction_message,
    execute_validated_decision,
    normalize_usage,
    parse_and_validate_decision,
)

__all__ = [
    "MAX_DECISION_ATTEMPTS",
    "MAX_TOOL_CALLS_PER_ATTEMPT",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_TIMEOUT_SECONDS",
    "PLAYER_INVOCATION_LIMITS",
    "PLAYER_PROVIDER_ROUTING",
    "DecisionAttemptRecord",
    "DecisionOutcome",
    "InvocationResponse",
    "PokerDecisionValidationError",
    "PlayerProviderStreamError",
    "StructuredDecisionError",
    "build_correction_message",
    "build_visible_state",
    "coordinate_decision",
    "create_player_agents",
    "create_player_model",
    "execute_validated_decision",
    "get_opponent_statistics",
    "invoke_player_once",
    "normalize_usage",
    "parse_and_validate_decision",
    "peek_opponent_card",
    "strategy_prompt_summary",
]
