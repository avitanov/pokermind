"""Tournament result document creation and hand replay snapshots."""

import copy
import logging

from task_3.pokermind.core.domain import (
    JUDGE_MODEL_ID,
    PLAYER_MODEL_ID,
    STARTING_STACK,
    TOTAL_CHIPS,
    HandState,
    TournamentState,
    TournamentStatus,
)
from task_3.pokermind.engine import BLIND_LEVELS, HAND_SEED_MULTIPLIER
from task_3.pokermind.results.checkpoint import (
    runtime_checkpoint,
    sync_runtime_checkpoint,
)

SCHEMA_VERSION = 2
LOGGER = logging.getLogger(__name__)


def _seat_map(values: dict[int, object]) -> dict[str, object]:
    return {str(seat): copy.deepcopy(value) for seat, value in sorted(values.items())}


def _player_stacks(state: TournamentState) -> dict[str, int]:
    return {str(seat): player.stack for seat, player in sorted(state.players.items())}


def _hand_record(result: dict[str, object], hand_number: int) -> dict[str, object]:
    hands = result["hands"]
    if not isinstance(hands, list):
        raise TypeError("Tournament result hands must be a list.")
    for record in hands:
        if isinstance(record, dict) and record.get("hand_number") == hand_number:
            return record
    raise ValueError(f"Hand {hand_number} has not been recorded.")


def _sync_hand_replay(record: dict[str, object], hand: HandState) -> None:
    record["board"] = [card.short_name() for card in hand.board]
    record["public_actions"] = copy.deepcopy(hand.action_history)
    record["all_in_cap"] = hand.all_in_cap
    record["refunds"] = copy.deepcopy(hand.refund_events)
    record["all_in_final_contributions"] = _seat_map(hand.all_in_final_contributions)
    record["showdown_results"] = {
        str(seat): {
            "rank": list(details["rank"]),
            "category": details["category"],
        }
        for seat, details in sorted(hand.showdown_results.items())
    }
    record["winning_rank"] = (
        list(hand.winning_rank) if hand.winning_rank is not None else None
    )
    record["winners"] = list(hand.winner_seats)
    record["pot_awards"] = _seat_map(hand.pot_awards)
    record["odd_chip_order"] = list(hand.odd_chip_order)
    record["eliminations"] = list(hand.eliminated_seats)
    record["completed"] = hand.completed


def create_tournament_result(
    state: TournamentState, *, started_at: str | None = None
) -> dict[str, object]:
    """Create the plain nested JSON record for one fresh tournament."""
    if state.hand_number != 0 or state.current_hand is not None:
        raise ValueError("Create the tournament result before the first hand starts.")
    result: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "tournament_id": state.tournament_id,
        "seed": state.seed,
        "initial_button": state.button_seat,
        "models": {
            "players": PLAYER_MODEL_ID,
            "judge": JUDGE_MODEL_ID,
        },
        "fixed_rules": {
            "starting_stack": STARTING_STACK,
            "total_chips": TOTAL_CHIPS,
            "blind_levels": [list(level) for level in BLIND_LEVELS],
            "final_blind_level_repeats": True,
            "hand_seed_multiplier": HAND_SEED_MULTIPLIER,
            "side_pots": False,
        },
        "status": TournamentStatus.IN_PROGRESS.value,
        "started_at": started_at,
        "completed_at": None,
        "players": [
            {
                "seat": seat,
                "name": player.name.value,
                "starting_stack": player.stack,
            }
            for seat, player in sorted(state.players.items())
        ],
        "initial_state": {
            "stacks": _player_stacks(state),
            "public_stats": {
                player.value: copy.deepcopy(statistics)
                for player, statistics in state.public_stats.items()
            },
            "peek_available": state.peek_available,
            "peek_observation": copy.deepcopy(state.adaptive_peek_observation),
        },
        "hands": [],
        "metrics": {},
        "winner": None,
        "placements": {},
        "judge_evaluations": [],
        "resume_history": [],
        "errors": [],
    }
    result["runtime_checkpoint"] = runtime_checkpoint(state)
    return result


def record_hand_start(result: dict[str, object], state: TournamentState) -> None:
    """Append the current dealt hand and its private replay area."""
    hand = state.current_hand
    if hand is None or hand.hand_seed is None:
        raise ValueError("A seeded hand must be active before it can be recorded.")
    hands = result["hands"]
    if not isinstance(hands, list):
        raise TypeError("Tournament result hands must be a list.")
    if any(
        isinstance(record, dict) and record.get("hand_number") == hand.hand_number
        for record in hands
    ):
        raise ValueError(f"Hand {hand.hand_number} is already recorded.")

    record: dict[str, object] = {
        "hand_number": hand.hand_number,
        "hand_seed": hand.hand_seed,
        "hole_cards": {
            str(seat): [card.short_name() for card in player.hole_cards]
            for seat, player in sorted(state.players.items())
            if player.hole_cards
        },
        "board": [],
        "blinds": {"small": hand.small_blind, "big": hand.big_blind},
        "positions": {
            "button": hand.button_seat,
            "small_blind": hand.small_blind_seat,
            "big_blind": hand.big_blind_seat,
            "preflop_first": hand.preflop_first_seat,
            "postflop_first": hand.postflop_first_seat,
        },
        "starting_stacks": _seat_map(hand.starting_stacks),
        "forced_blinds": copy.deepcopy(hand.forced_blinds),
        "decisions": [],
        "public_actions": [],
        "all_in_cap": None,
        "refunds": [],
        "all_in_final_contributions": {},
        "showdown_results": {},
        "winning_rank": None,
        "winners": [],
        "pot_awards": {},
        "odd_chip_order": [],
        "eliminations": [],
        "ending_stacks": None,
        "completed": False,
    }
    _sync_hand_replay(record, hand)
    hands.append(record)
    sync_runtime_checkpoint(result, state)
    LOGGER.info("Tournament %s hand %s started", state.tournament_id, hand.hand_number)
