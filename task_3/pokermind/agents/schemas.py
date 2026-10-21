"""Decision results, attempts, and categorized agent-layer errors."""

from collections.abc import Callable
from dataclasses import dataclass

from strands.agent import AgentResult

from task_3.pokermind.core.domain import PokerDecision


class StructuredDecisionError(ValueError):
    """A model result did not satisfy the structured output contract."""

    category = "structured_output"


class PokerDecisionValidationError(ValueError):
    """A typed proposal failed deterministic poker validation."""

    category = "poker_validation"

    def __init__(self, errors: list[str], legal: list[dict[str, object]]) -> None:
        self.errors = errors
        self.legal_actions = legal
        super().__init__("; ".join(errors))


class PlayerProviderStreamError(ConnectionError):
    """A provider rejected or interrupted an otherwise valid model stream."""


@dataclass(slots=True)
class InvocationResponse:
    """One bounded graph result plus sanitized tool activity."""

    result: AgentResult
    tool_events: list[dict[str, object]]
    tool_call_count: int


@dataclass(slots=True)
class DecisionAttemptRecord:
    """Sanitized record of one model invocation attempt."""

    attempt: int
    category: str
    error: str | None
    proposal: dict[str, object] | None
    tool_events: list[dict[str, object]]
    tool_call_count: int
    usage: dict[str, int | bool | None]
    retry: bool
    prompt: str


@dataclass(slots=True)
class DecisionOutcome:
    """Final result of one bounded agent decision coordination."""

    decision: PokerDecision | None
    attempts: list[DecisionAttemptRecord]
    used_fallback: bool
    api_failed: bool
    visible_state: dict[str, object]
    legal_actions: list[dict[str, object]]


InvokeOnce = Callable[[str, int], AgentResult | InvocationResponse]
