"""Decision, completion, placement, and Judge records."""

import copy
import logging

from task_3.pokermind.agents import DecisionAttemptRecord, DecisionOutcome
from task_3.pokermind.core.domain import (
    ActionType,
    TournamentState,
    TournamentStatus,
)
from task_3.pokermind.results.document import (
    _hand_record,
    _player_stacks,
    _sync_hand_replay,
)
from task_3.pokermind.results.metrics import compute_metrics
from task_3.pokermind.results.checkpoint import sync_runtime_checkpoint

LOGGER = logging.getLogger(__name__)


def _attempt_record(attempt: DecisionAttemptRecord) -> dict[str, object]:
    return {
        "attempt": attempt.attempt,
        "category": attempt.category,
        "error": attempt.error,
        "proposal": copy.deepcopy(attempt.proposal),
        "tool_events": copy.deepcopy(attempt.tool_events),
        "tool_call_count": attempt.tool_call_count,
        "usage": copy.deepcopy(attempt.usage),
        "retry": attempt.retry,
        "prompt": attempt.prompt,
    }


def _decision_usage(attempts: list[dict[str, object]]) -> dict[str, object]:
    available = [
        attempt["usage"]
        for attempt in attempts
        if isinstance(attempt.get("usage"), dict)
        and attempt["usage"].get("usage_available") is True
    ]
    if not available:
        return {
            "usage_available": False,
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }
    return {
        "usage_available": True,
        "input_tokens": sum(int(usage["input_tokens"]) for usage in available),
        "output_tokens": sum(int(usage["output_tokens"]) for usage in available),
        "total_tokens": sum(int(usage["total_tokens"]) for usage in available),
    }


def record_decision(
    result: dict[str, object],
    state: TournamentState,
    actor: int,
    outcome: DecisionOutcome,
) -> None:
    """Append one bounded decision outcome after its final action was executed."""
    hand_number = int(outcome.visible_state["hand_number"])
    hand_record = _hand_record(result, hand_number)
    decisions = hand_record["decisions"]
    if not isinstance(decisions, list):
        raise TypeError("Hand decisions must be a list.")

    attempts = [_attempt_record(attempt) for attempt in outcome.attempts]
    tool_events = [
        {"attempt": attempt["attempt"], **copy.deepcopy(event)}
        for attempt in attempts
        for event in attempt["tool_events"]
        if isinstance(event, dict)
    ]
    decision = outcome.decision
    source = "fallback" if outcome.used_fallback else "agent"
    final_executed = None
    if decision is not None:
        final_executed = {
            "source": source,
            "ACTION": decision.action.value,
            "AMOUNT": decision.amount,
            "REASON": decision.reason,
        }
    failure_categories = [
        str(attempt["category"])
        for attempt in attempts
        if attempt["category"] != "success"
    ]
    visible_players = outcome.visible_state.get("players")
    if not isinstance(visible_players, dict):
        raise TypeError("Visible state players must be a dictionary.")
    actor_visible = visible_players.get(str(actor))
    if not isinstance(actor_visible, dict):
        raise ValueError("The acting player's visible stack is missing.")
    all_in = bool(
        decision is not None
        and decision.action in {ActionType.CALL, ActionType.RAISE}
        and decision.amount == actor_visible["stack"]
    )

    record: dict[str, object] = {
        "agent": state.players[actor].name.value,
        "strategy": state.players[actor].name.value,
        "actor_seat": actor,
        "hand_number": hand_number,
        "street": outcome.visible_state["street"],
        "visible_state": copy.deepcopy(outcome.visible_state),
        "legal_actions": copy.deepcopy(outcome.legal_actions),
        "tool_events": tool_events,
        "attempts": attempts,
        "failure_category": failure_categories[-1] if failure_categories else None,
        "failure_categories": failure_categories,
        "retry_used": len(attempts) > 1,
        "fallback_used": outcome.used_fallback,
        "api_failed": outcome.api_failed,
        "usage": _decision_usage(attempts),
        "ACTION": decision.action.value if decision is not None else None,
        "AMOUNT": decision.amount if decision is not None else None,
        "REASON": decision.reason if decision is not None else None,
        "final_executed": final_executed,
        "all_in": all_in,
        "stacks_after": _player_stacks(state),
        "pot_after": state.current_hand.pot if state.current_hand is not None else 0,
    }
    decisions.append(record)
    record_hand_progress(result, state)
    LOGGER.info(
        "Tournament %s hand %s %s decision recorded",
        state.tournament_id,
        hand_number,
        state.players[actor].name.value,
    )


def record_hand_progress(result: dict[str, object], state: TournamentState) -> None:
    """Synchronize dealt board, actions, all-in events, and replay outcomes."""
    hand = state.current_hand
    if hand is None:
        raise ValueError("No current hand is available to synchronize.")
    record = _hand_record(result, hand.hand_number)
    _sync_hand_replay(record, hand)
    sync_runtime_checkpoint(result, state)


def record_hand_completion(result: dict[str, object], state: TournamentState) -> None:
    """Finalize replay fields for the current completed hand."""
    hand = state.current_hand
    if hand is None or not hand.completed:
        raise ValueError("The current hand must be completed before recording it.")
    record_hand_progress(result, state)
    record = _hand_record(result, hand.hand_number)
    record["ending_stacks"] = _player_stacks(state)
    result["metrics"] = compute_metrics(result)
    sync_runtime_checkpoint(result, state)
    LOGGER.info(
        "Tournament %s hand %s completed", state.tournament_id, hand.hand_number
    )


def _placements(result: dict[str, object], state: TournamentState) -> dict[str, int]:
    if state.status is not TournamentStatus.COMPLETED or state.winner_seat is None:
        return {}
    elimination_hand: dict[int, int] = {}
    hands = result["hands"]
    if not isinstance(hands, list):
        raise TypeError("Tournament result hands must be a list.")
    for hand in hands:
        if not isinstance(hand, dict):
            continue
        for seat in hand.get("eliminations", []):
            elimination_hand[int(seat)] = int(hand["hand_number"])
    ordered = [state.winner_seat] + sorted(
        (seat for seat in state.players if seat != state.winner_seat),
        key=lambda seat: (-elimination_hand.get(seat, -1), seat),
    )
    return {
        state.players[seat].name.value: place for place, seat in enumerate(ordered, 1)
    }


def finalize_tournament_result(
    result: dict[str, object],
    state: TournamentState,
    *,
    completed_at: str | None = None,
) -> None:
    """Finalize status, winner, placements, errors, and deterministic metrics."""
    if state.status is TournamentStatus.IN_PROGRESS:
        raise ValueError("An in-progress tournament cannot be finalized.")
    result["status"] = state.status.value
    result["completed_at"] = completed_at
    result["winner"] = (
        state.players[state.winner_seat].name.value
        if state.winner_seat is not None
        else None
    )
    result["placements"] = _placements(result, state)
    errors = result["errors"]
    if not isinstance(errors, list):
        raise TypeError("Tournament result errors must be a list.")
    if state.failure is not None:
        errors.append(copy.deepcopy(state.failure))
    result["metrics"] = compute_metrics(result)
    sync_runtime_checkpoint(result, state)
    if state.winner_seat is not None:
        LOGGER.info(
            "Tournament %s completed; winner=%s",
            state.tournament_id,
            state.players[state.winner_seat].name.value,
        )


def add_judge_evaluation(
    result: dict[str, object], evaluation: dict[str, object]
) -> None:
    """Attach one Judge result without changing any poker outcome fields."""
    evaluations = result["judge_evaluations"]
    if not isinstance(evaluations, list):
        raise TypeError("Judge evaluations must be a list.")
    player = evaluation.get("player")
    if not isinstance(player, str) or not player:
        raise ValueError("A Judge evaluation requires an evaluated player.")
    matching_indexes = [
        index
        for index, existing in enumerate(evaluations)
        if isinstance(existing, dict) and existing.get("player") == player
    ]
    if len(matching_indexes) > 1:
        raise ValueError(f"Multiple Judge records already exist for {player}.")
    copied = copy.deepcopy(evaluation)
    if matching_indexes:
        index = matching_indexes[0]
        existing = evaluations[index]
        if isinstance(existing, dict) and existing.get("status") == "completed":
            raise ValueError(
                f"A completed Judge evaluation already exists for {player}."
            )
        evaluations[index] = copied
    else:
        evaluations.append(copied)
    result["metrics"] = compute_metrics(result)
