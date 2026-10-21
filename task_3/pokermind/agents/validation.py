"""Structured decision parsing, poker validation, and deterministic fallback."""

import json

from pydantic import ValidationError
from strands.agent import AgentResult

from task_3.pokermind.agents.configuration import (
    _LIMIT_STOP_REASONS,
    API_FALLBACK_REASON,
    FALLBACK_REASON,
)
from task_3.pokermind.agents.schemas import (
    DecisionAttemptRecord,
    InvocationResponse,
    PokerDecisionValidationError,
    StructuredDecisionError,
)
from task_3.pokermind.agents.state import _serialize_legal_actions
from task_3.pokermind.core.domain import (
    ActionDecision,
    ActionType,
    PokerDecision,
    TournamentState,
    TournamentStatus,
)
from task_3.pokermind.engine import apply_action, legal_actions, validate_action


def _validation_legal_actions(
    state: TournamentState, actor: int
) -> list[dict[str, object]]:
    return _serialize_legal_actions(state, actor)


def parse_and_validate_decision(
    state: TournamentState, actor: int, proposal: object
) -> PokerDecision:
    """Parse structured output and validate it without mutating poker state."""
    payload = (
        proposal.structured_output if isinstance(proposal, AgentResult) else proposal
    )
    if payload is None:
        if (
            isinstance(proposal, AgentResult)
            and proposal.stop_reason in _LIMIT_STOP_REASONS
        ):
            raise StructuredDecisionError(
                f"Agent stopped at {proposal.stop_reason} without structured output."
            )
        raise StructuredDecisionError("Agent result is missing structured output.")
    try:
        decision = (
            payload
            if isinstance(payload, PokerDecision)
            else PokerDecision.model_validate(payload)
        )
    except ValidationError as error:
        action_errors = [
            detail for detail in error.errors() if detail.get("loc") == ("ACTION",)
        ]
        if action_errors and len(action_errors) == len(error.errors()):
            raise PokerDecisionValidationError(
                ["ACTION must be FOLD, CHECK, CALL, or RAISE."],
                _validation_legal_actions(state, actor),
            ) from error
        raise StructuredDecisionError(f"Invalid structured output: {error}") from error

    engine_decision = ActionDecision(decision.action, decision.amount)
    errors = validate_action(state, actor, engine_decision)
    if errors:
        raise PokerDecisionValidationError(
            errors, _validation_legal_actions(state, actor)
        )
    return decision


def build_correction_message(error: PokerDecisionValidationError) -> str:
    """Build a decision-local correction containing exact current legal actions."""
    details = json.dumps(error.legal_actions, sort_keys=True, separators=(",", ":"))
    return (
        f"Poker validation failed: {'; '.join(error.errors)} Legal actions: {details}"
    )


def execute_validated_decision(
    state: TournamentState, actor: int, decision: PokerDecision
) -> None:
    """Apply one validated proposal and preserve only its concise public reason."""
    engine_decision = ActionDecision(decision.action, decision.amount)
    apply_action(state, actor, engine_decision)
    hand = state.current_hand
    if hand is None or not hand.action_history:
        raise AssertionError(
            "An executed decision must create one public action record."
        )
    hand.action_history[-1]["reason"] = decision.reason


def unavailable_usage() -> dict[str, int | bool | None]:
    """The token-usage record used whenever no usage could be observed."""
    return {
        "usage_available": False,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }


def normalize_usage(result: AgentResult | None) -> dict[str, int | bool | None]:
    """Normalize observed Strands token usage without estimating missing values."""
    if result is None:
        return unavailable_usage()
    metrics = result.metrics
    if not metrics.agent_invocations or not any(
        invocation.cycles for invocation in metrics.agent_invocations
    ):
        return unavailable_usage()
    usage = metrics.accumulated_usage
    keys = ("inputTokens", "outputTokens", "totalTokens")
    if not all(isinstance(usage.get(key), int) for key in keys):
        return unavailable_usage()
    return {
        "usage_available": True,
        "input_tokens": int(usage["inputTokens"]),
        "output_tokens": int(usage["outputTokens"]),
        "total_tokens": int(usage["totalTokens"]),
    }


def _structured_correction_message(
    state: TournamentState, actor: int, error: StructuredDecisionError
) -> str:
    legal = json.dumps(
        _validation_legal_actions(state, actor),
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"Structured output failed: {error} Legal actions: {legal}"


def _invocation_parts(
    response: AgentResult | InvocationResponse,
) -> tuple[AgentResult, list[dict[str, object]], int]:
    if isinstance(response, InvocationResponse):
        return response.result, response.tool_events, response.tool_call_count
    return response, [], 0


def _proposal_record(result: AgentResult) -> dict[str, object] | None:
    proposal = result.structured_output
    if not isinstance(proposal, PokerDecision):
        return None
    return proposal.model_dump(by_alias=True)


def _fallback_decision(state: TournamentState, actor: int) -> PokerDecision:
    actions = legal_actions(state, actor)
    by_type = {action.action: action for action in actions}
    if ActionType.CHECK in by_type:
        action = ActionType.CHECK
        amount = 0
    elif ActionType.FOLD in by_type:
        action = ActionType.FOLD
        amount = 0
    elif ActionType.CALL in by_type:
        action = ActionType.CALL
        exact = by_type[action].amount
        if exact is None:
            raise AssertionError("A legal fallback call requires an exact amount.")
        amount = exact
    else:
        raise AssertionError("No deterministic fallback action is legal.")
    decision = PokerDecision(ACTION=action, AMOUNT=amount, REASON=FALLBACK_REASON)
    return parse_and_validate_decision(state, actor, decision)


def _api_fallback_decision(state: TournamentState, actor: int) -> PokerDecision:
    actions = legal_actions(state, actor)
    if any(action.action is ActionType.FOLD for action in actions):
        decision = PokerDecision(
            ACTION=ActionType.FOLD,
            AMOUNT=0,
            REASON=API_FALLBACK_REASON,
        )
        return parse_and_validate_decision(state, actor, decision)
    return _fallback_decision(state, actor)


def _revert_uncommitted_peek(
    state: TournamentState,
    peek_available_before: bool,
    peek_observation_before: dict[str, int | str] | None,
    tool_events: list[dict[str, object]],
) -> None:
    """Give the one-time peek back if the attempt that spent it is discarded.

    A peek consumes ``state.peek_available`` the moment the tool runs, but an
    attempt whose decision is later rejected (or whose API call crashes) never
    commits. Restoring the flag lets a retry or a later decision peek again, and
    marking the throwaway peek event keeps it from counting as the tournament's
    one successful peek in the audit.
    """
    if state.peek_available == peek_available_before:
        return
    state.peek_available = peek_available_before
    state.adaptive_peek_observation = peek_observation_before
    for event in tool_events:
        if (
            isinstance(event, dict)
            and event.get("tool") == "peek_opponent_card"
            and isinstance(event.get("result"), dict)
            and event["result"].get("ok") is True
        ):
            event["reverted"] = True
            event["result"]["ok"] = False
            event["result"]["error"] = "reverted: decision attempt was discarded"


def _mark_api_failure(
    state: TournamentState,
    actor: int,
    attempts: list[DecisionAttemptRecord],
) -> None:
    hand = state.current_hand
    if hand is None:
        raise ValueError("No hand is active.")
    failure: dict[str, object] = {
        "category": "api_failure",
        "message": "Decision API failed on the final allowed attempt.",
        "hand_number": hand.hand_number,
        "street": hand.street.value,
        "actor": actor,
        "attempts": len(attempts),
    }
    state.status = TournamentStatus.FAILED
    state.failure = failure
    state.events.append({"event": "tournament_failed", **failure})
