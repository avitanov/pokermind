"""Compact visibility-safe player traces for post-tournament evaluation."""

import copy
import json

from task_3.pokermind.agents import strategy_prompt_summary
from task_3.pokermind.core.domain import PlayerName


def _player_seat(tournament_json: dict[str, object], player: PlayerName) -> int:
    players = tournament_json.get("players")
    if not isinstance(players, list):
        raise TypeError("Tournament players must be a list.")
    matches = [
        entry
        for entry in players
        if isinstance(entry, dict) and entry.get("name") == player.value
    ]
    if len(matches) != 1:
        raise ValueError(f"Tournament must contain exactly one {player.value} player.")
    return int(matches[0]["seat"])


def _position_name(positions: dict[str, object], seat: int) -> str:
    roles = [
        name
        for name in ("button", "small_blind", "big_blind")
        if positions.get(name) == seat
    ]
    return "/".join(roles) if roles else "other"


def _compact_legal_actions(actions: object) -> list[dict[str, object]]:
    if not isinstance(actions, list):
        raise TypeError("Recorded legal actions must be a list.")
    compact: list[dict[str, object]] = []
    for action in actions:
        if not isinstance(action, dict):
            raise TypeError("Each legal action must be a dictionary.")
        compact.append(
            {key: value for key, value in action.items() if value is not None}
        )
    return compact


def _compact_tool_events(events: object) -> list[dict[str, object]]:
    if not isinstance(events, list):
        raise TypeError("Recorded tool events must be a list.")
    return [
        {
            "tool": event.get("tool"),
            "input": copy.deepcopy(event.get("input")),
            "result": copy.deepcopy(event.get("result")),
        }
        for event in events
        if isinstance(event, dict)
    ]


def compact_player_trace(
    tournament_json: dict[str, object], player: PlayerName
) -> dict[str, object]:
    """Build a compact Judge input from only one player's recorded visibility."""
    if tournament_json.get("status") != "completed":
        raise ValueError("Judge evaluation requires a completed tournament record.")
    seat = _player_seat(tournament_json, player)
    hands = tournament_json.get("hands")
    metrics = tournament_json.get("metrics")
    if not isinstance(hands, list) or not isinstance(metrics, dict):
        raise TypeError("Tournament hands and metrics have invalid types.")
    player_metrics = metrics.get("players")
    if not isinstance(player_metrics, dict):
        raise TypeError("Tournament player metrics are missing.")

    decisions: list[dict[str, object]] = []
    for hand in hands:
        if not isinstance(hand, dict):
            raise TypeError("Each recorded hand must be a dictionary.")
        for decision in hand.get("decisions", []):
            if not isinstance(decision, dict) or decision.get("agent") != player.value:
                continue
            if not isinstance(decision.get("final_executed"), dict):
                continue
            visible = decision.get("visible_state")
            if not isinstance(visible, dict):
                raise TypeError("A Judge decision requires its recorded visible state.")
            positions = visible.get("positions")
            visible_players = visible.get("players")
            if not isinstance(positions, dict) or not isinstance(visible_players, dict):
                raise TypeError("Recorded positions and visible stacks are required.")
            pot_awards = hand.get("pot_awards", {})
            ending_stacks = hand.get("ending_stacks", {})
            if not isinstance(pot_awards, dict) or not isinstance(ending_stacks, dict):
                raise TypeError("Recorded hand outcomes have invalid types.")
            decisions.append(
                {
                    "hand": int(decision["hand_number"]),
                    "street": decision["street"],
                    "position": _position_name(positions, seat),
                    "own_cards": copy.deepcopy(visible.get("hole_cards", [])),
                    "board": copy.deepcopy(visible.get("board", [])),
                    "pot": visible.get("pot"),
                    "stacks": {
                        key: value.get("stack")
                        for key, value in visible_players.items()
                        if isinstance(value, dict)
                    },
                    "legal_actions": _compact_legal_actions(
                        decision.get("legal_actions")
                    ),
                    "tool_events": _compact_tool_events(
                        decision.get("tool_events", [])
                    ),
                    "executed": copy.deepcopy(decision.get("final_executed")),
                    "retry": decision.get("retry_used") is True,
                    "fallback": decision.get("fallback_used") is True,
                    "eventual_outcome": {
                        "won_hand": seat in hand.get("winners", []),
                        "chips_awarded": int(pot_awards.get(str(seat), 0)),
                        "ending_stack": int(ending_stacks.get(str(seat), 0)),
                    },
                }
            )
    if not decisions:
        raise ValueError(f"No recorded decisions exist for {player.value}.")

    return {
        "tournament_id": tournament_json.get("tournament_id"),
        "player": player.value,
        "strategy_summary": strategy_prompt_summary(player),
        "tool_usage_applicable": player is PlayerName.ADAPTIVE,
        "metrics": copy.deepcopy(player_metrics.get(player.value)),
        "decisions": decisions,
    }


def render_judge_prompt(compact_trace: dict[str, object]) -> str:
    """Render one compact, deterministic Judge prompt without raw tournament JSON."""
    return json.dumps(compact_trace, sort_keys=True, separators=(",", ":"))
