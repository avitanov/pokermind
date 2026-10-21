"""The two bounded information tools available only to Adaptive."""

import copy
import random

from strands import ToolContext, tool

from task_3.pokermind.core.domain import PlayerName, TournamentState


MAX_TOOL_CALLS_PER_ATTEMPT = 2


def _record_tool_event(
    tool_context: ToolContext,
    tool_name: str,
    opponent: str,
    result: dict[str, object],
) -> None:
    events = tool_context.invocation_state.get("tool_events")
    if isinstance(events, list):
        event: dict[str, object] = {
            "tool": tool_name,
            "input": {"opponent": opponent},
            "result": copy.deepcopy(result),
        }
        if result.get("ok") is False:
            event["category"] = "tool_result"
        events.append(event)


def _tool_error(
    tool_context: ToolContext, tool_name: str, opponent: str, message: str
) -> dict[str, object]:
    result: dict[str, object] = {"ok": False, "error": message}
    _record_tool_event(tool_context, tool_name, opponent, result)
    return result


def _adaptive_state(
    opponent: str, tool_context: ToolContext, tool_name: str
) -> tuple[TournamentState | None, PlayerName | None, dict[str, object] | None]:
    invocation_state = tool_context.invocation_state
    if invocation_state.get("actor") != PlayerName.ADAPTIVE.value:
        return (
            None,
            None,
            _tool_error(
                tool_context, tool_name, opponent, "tool is available only to Adaptive"
            ),
        )
    state = invocation_state.get("tournament_state")
    if not isinstance(state, TournamentState):
        return (
            None,
            None,
            _tool_error(
                tool_context, tool_name, opponent, "tournament state is unavailable"
            ),
        )
    try:
        target = PlayerName(opponent)
    except ValueError:
        return (
            state,
            None,
            _tool_error(
                tool_context, tool_name, opponent, "unknown tournament opponent"
            ),
        )
    if target is PlayerName.ADAPTIVE:
        return (
            state,
            target,
            _tool_error(
                tool_context, tool_name, opponent, "Adaptive cannot target itself"
            ),
        )
    return state, target, None


def _reserve_tool_call(
    opponent: str, tool_context: ToolContext, tool_name: str
) -> dict[str, object] | None:
    if tool_context.invocation_state.get("actor") != PlayerName.ADAPTIVE.value:
        return None
    count = tool_context.invocation_state.get("tool_call_count", 0)
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise TypeError("tool_call_count must be a non-negative integer")
    if count >= MAX_TOOL_CALLS_PER_ATTEMPT:
        return _tool_error(
            tool_context,
            tool_name,
            opponent,
            "tool call limit reached for this decision",
        )
    tool_context.invocation_state["tool_call_count"] = count + 1
    return None


@tool(context=True)
def get_opponent_statistics(
    opponent: str, tool_context: ToolContext
) -> dict[str, object]:
    """Return compact public action statistics for one current-tournament opponent.

    Args:
        opponent: Exact player name, Conservative or Aggressive.
        tool_context: Strands invocation context supplied automatically.
    """
    tool_name = "get_opponent_statistics"
    limit_error = _reserve_tool_call(opponent, tool_context, tool_name)
    if limit_error is not None:
        return limit_error
    state, target, error = _adaptive_state(opponent, tool_context, tool_name)
    if error is not None:
        return error
    if state is None or target is None:
        raise AssertionError("Validated statistics access requires state and target.")

    statistics = state.public_stats[target]
    decisions = int(statistics["decisions"])
    counts = {
        "fold": int(statistics["folds"]),
        "check": int(statistics["checks"]),
        "call": int(statistics["calls"]),
        "raise": int(statistics["raises"]),
        "all_in": int(statistics["all_ins"]),
    }
    denominator = decisions or 1
    result: dict[str, object] = {
        "ok": True,
        "opponent": target.value,
        "decisions": decisions,
        "counts": counts,
        "rates": {
            action: counts[action] / denominator
            for action in ("fold", "check", "call", "raise")
        },
        "aggression_frequency": counts["raise"] / denominator,
        "voluntary_chips": int(statistics["voluntary_chips"]),
        "recent_actions": copy.deepcopy(statistics["recent_actions"]),
    }
    _record_tool_event(tool_context, tool_name, opponent, result)
    return result


@tool(context=True)
def peek_opponent_card(opponent: str, tool_context: ToolContext) -> dict[str, object]:
    """Reveal one reproducibly selected current hole card once per tournament.

    Args:
        opponent: Exact player name, Conservative or Aggressive.
        tool_context: Strands invocation context supplied automatically.
    """
    tool_name = "peek_opponent_card"
    limit_error = _reserve_tool_call(opponent, tool_context, tool_name)
    if limit_error is not None:
        return limit_error
    state, target, error = _adaptive_state(opponent, tool_context, tool_name)
    if error is not None:
        return error
    if state is None or target is None:
        raise AssertionError("Validated peek access requires state and target.")
    if not state.peek_available:
        return _tool_error(
            tool_context,
            tool_name,
            opponent,
            "peek already used in this tournament",
        )

    target_player = next(
        player for player in state.players.values() if player.name is target
    )
    if target_player.eliminated:
        return _tool_error(
            tool_context, tool_name, opponent, "target opponent is eliminated"
        )
    hand = state.current_hand
    if hand is None:
        return _tool_error(
            tool_context, tool_name, opponent, "no current hand is active"
        )
    if len(target_player.hole_cards) != 2:
        return _tool_error(
            tool_context,
            tool_name,
            opponent,
            "target opponent does not have two current hole cards",
        )

    card = target_player.hole_cards[random.Random(state.peek_seed).randrange(2)]
    observation: dict[str, int | str] = {
        "opponent": target.value,
        "card": card.short_name(),
        "hand_number": hand.hand_number,
    }
    state.peek_available = False
    state.adaptive_peek_observation = observation
    result: dict[str, object] = {"ok": True, **observation}
    _record_tool_event(tool_context, tool_name, opponent, result)
    return result
