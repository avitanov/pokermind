"""JSON-safe runtime checkpoints for exact tournament continuation."""

import copy

from task_3.pokermind.core.domain import (
    Card,
    HandState,
    PlayerName,
    PlayerState,
    Street,
    TournamentState,
    TournamentStatus,
)
from task_3.pokermind.engine import assert_chip_invariants

CHECKPOINT_VERSION = 1


def _cards(cards: list[Card]) -> list[str]:
    return [card.short_name() for card in cards]


def _json_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return copy.deepcopy(value)


def _int_map(values: dict[int, object]) -> dict[str, object]:
    return {str(key): _json_value(value) for key, value in sorted(values.items())}


def _serialize_hand(hand: HandState | None) -> dict[str, object] | None:
    if hand is None:
        return None
    return {
        "hand_number": hand.hand_number,
        "street": hand.street.value,
        "small_blind": hand.small_blind,
        "big_blind": hand.big_blind,
        "button_seat": hand.button_seat,
        "small_blind_seat": hand.small_blind_seat,
        "big_blind_seat": hand.big_blind_seat,
        "preflop_first_seat": hand.preflop_first_seat,
        "postflop_first_seat": hand.postflop_first_seat,
        "starting_stacks": _int_map(hand.starting_stacks),
        "hand_seed": hand.hand_seed,
        "deck": _cards(hand.deck),
        "pot": hand.pot,
        "board": _cards(hand.board),
        "forced_blinds": _json_value(hand.forced_blinds),
        "current_bet": hand.current_bet,
        "last_full_raise_size": hand.last_full_raise_size,
        "pending_to_act": list(hand.pending_to_act),
        "round_complete": hand.round_complete,
        "uncontested_winner_seat": hand.uncontested_winner_seat,
        "action_history": _json_value(hand.action_history),
        "completed": hand.completed,
        "winner_seats": list(hand.winner_seats),
        "pot_awards": _int_map(hand.pot_awards),
        "odd_chip_order": list(hand.odd_chip_order),
        "showdown_results": _int_map(hand.showdown_results),
        "winning_rank": list(hand.winning_rank) if hand.winning_rank else None,
        "all_in_resolution": hand.all_in_resolution,
        "all_in_cap": hand.all_in_cap,
        "refund_events": _json_value(hand.refund_events),
        "all_in_final_contributions": _int_map(hand.all_in_final_contributions),
        "eliminated_seats": list(hand.eliminated_seats),
    }


def runtime_checkpoint(state: TournamentState) -> dict[str, object]:
    """Serialize all deterministic runtime state needed to continue execution."""
    return {
        "checkpoint_version": CHECKPOINT_VERSION,
        "tournament_id": state.tournament_id,
        "seed": state.seed,
        "button_seat": state.button_seat,
        "hand_number": state.hand_number,
        "status": state.status.value,
        "failure": _json_value(state.failure),
        "completed": state.completed,
        "winner_seat": state.winner_seat,
        "players": {
            str(seat): {
                "seat": player.seat,
                "name": player.name.value,
                "stack": player.stack,
                "eliminated": player.eliminated,
                "hole_cards": _cards(player.hole_cards),
                "folded": player.folded,
                "all_in": player.all_in,
                "hand_contribution": player.hand_contribution,
                "street_contribution": player.street_contribution,
            }
            for seat, player in sorted(state.players.items())
        },
        "current_hand": _serialize_hand(state.current_hand),
        "public_stats": {
            player.value: _json_value(statistics)
            for player, statistics in state.public_stats.items()
        },
        "peek_available": state.peek_available,
        "peek_seed": state.peek_seed,
        "adaptive_peek_observation": _json_value(state.adaptive_peek_observation),
        "events": _json_value(state.events),
        "counters": _json_value(state.counters),
    }


def sync_runtime_checkpoint(result: dict[str, object], state: TournamentState) -> None:
    """Replace the result's private runtime checkpoint with current state."""
    result["runtime_checkpoint"] = runtime_checkpoint(state)


def _restore_hand(payload: object) -> HandState | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("Runtime checkpoint current_hand must be an object.")
    showdown = copy.deepcopy(payload["showdown_results"])
    if not isinstance(showdown, dict):
        raise ValueError("Checkpoint showdown results must be an object.")
    return HandState(
        hand_number=int(payload["hand_number"]),
        street=Street(str(payload["street"])),
        small_blind=int(payload["small_blind"]),
        big_blind=int(payload["big_blind"]),
        button_seat=int(payload["button_seat"]),
        small_blind_seat=int(payload["small_blind_seat"]),
        big_blind_seat=int(payload["big_blind_seat"]),
        preflop_first_seat=int(payload["preflop_first_seat"]),
        postflop_first_seat=int(payload["postflop_first_seat"]),
        starting_stacks={
            int(key): int(value)
            for key, value in dict(payload["starting_stacks"]).items()
        },
        hand_seed=(int(payload["hand_seed"]) if payload["hand_seed"] else None),
        deck=[Card.parse(card) for card in payload["deck"]],
        pot=int(payload["pot"]),
        board=[Card.parse(card) for card in payload["board"]],
        forced_blinds=copy.deepcopy(payload["forced_blinds"]),
        current_bet=int(payload["current_bet"]),
        last_full_raise_size=int(payload["last_full_raise_size"]),
        pending_to_act=[int(seat) for seat in payload["pending_to_act"]],
        round_complete=bool(payload["round_complete"]),
        uncontested_winner_seat=payload["uncontested_winner_seat"],
        action_history=copy.deepcopy(payload["action_history"]),
        completed=bool(payload["completed"]),
        winner_seats=[int(seat) for seat in payload["winner_seats"]],
        pot_awards={
            int(key): int(value) for key, value in dict(payload["pot_awards"]).items()
        },
        odd_chip_order=[int(seat) for seat in payload["odd_chip_order"]],
        showdown_results={int(key): value for key, value in showdown.items()},
        winning_rank=(
            tuple(int(value) for value in payload["winning_rank"])
            if payload["winning_rank"] is not None
            else None
        ),
        all_in_resolution=bool(payload["all_in_resolution"]),
        all_in_cap=(int(payload["all_in_cap"]) if payload["all_in_cap"] else None),
        refund_events=copy.deepcopy(payload["refund_events"]),
        all_in_final_contributions={
            int(key): int(value)
            for key, value in dict(payload["all_in_final_contributions"]).items()
        },
        eliminated_seats=[int(seat) for seat in payload["eliminated_seats"]],
    )


def restore_runtime_checkpoint(result: dict[str, object]) -> TournamentState:
    """Restore and validate deterministic state from a tournament result."""
    payload = result.get("runtime_checkpoint")
    if not isinstance(payload, dict):
        raise ValueError("Snapshot does not contain a resumable runtime checkpoint.")
    if payload.get("checkpoint_version") != CHECKPOINT_VERSION:
        raise ValueError("Snapshot runtime checkpoint version is unsupported.")
    if payload.get("tournament_id") != result.get("tournament_id"):
        raise ValueError("Checkpoint tournament ID does not match the result.")
    if payload.get("seed") != result.get("seed"):
        raise ValueError("Checkpoint seed does not match the result.")

    raw_players = payload.get("players")
    if not isinstance(raw_players, dict):
        raise ValueError("Checkpoint players must be an object.")
    players = {
        int(seat): PlayerState(
            seat=int(player["seat"]),
            name=PlayerName(str(player["name"])),
            stack=int(player["stack"]),
            eliminated=bool(player["eliminated"]),
            hole_cards=[Card.parse(card) for card in player["hole_cards"]],
            folded=bool(player["folded"]),
            all_in=bool(player["all_in"]),
            hand_contribution=int(player["hand_contribution"]),
            street_contribution=int(player["street_contribution"]),
        )
        for seat, player in raw_players.items()
        if isinstance(player, dict)
    }
    raw_stats = payload.get("public_stats")
    if not isinstance(raw_stats, dict):
        raise ValueError("Checkpoint public statistics must be an object.")
    state = TournamentState(
        tournament_id=str(payload["tournament_id"]),
        seed=int(payload["seed"]),
        players=players,
        button_seat=int(payload["button_seat"]),
        hand_number=int(payload["hand_number"]),
        current_hand=_restore_hand(payload.get("current_hand")),
        public_stats={
            PlayerName(name): copy.deepcopy(statistics)
            for name, statistics in raw_stats.items()
        },
        peek_available=bool(payload["peek_available"]),
        peek_seed=int(payload["peek_seed"]),
        adaptive_peek_observation=copy.deepcopy(payload["adaptive_peek_observation"]),
        status=TournamentStatus(str(payload["status"])),
        failure=copy.deepcopy(payload["failure"]),
        completed=bool(payload["completed"]),
        winner_seat=payload["winner_seat"],
        events=copy.deepcopy(payload["events"]),
        counters={key: int(value) for key, value in payload["counters"].items()},
    )
    assert_chip_invariants(state)
    cards = [card for player in players.values() for card in player.hole_cards]
    if state.current_hand is not None:
        cards.extend(state.current_hand.board)
        cards.extend(state.current_hand.deck)
        if len(cards) != 52 or len(set(cards)) != 52:
            raise ValueError("Checkpoint does not contain exactly 52 unique cards.")
    return state


def prepare_resumed_result(result: dict[str, object], state: TournamentState) -> None:
    """Reset only terminal runtime markers while retaining failure evidence."""
    if state.status is TournamentStatus.COMPLETED:
        raise ValueError("A completed tournament cannot be resumed.")
    history = result.setdefault("resume_history", [])
    if not isinstance(history, list):
        raise ValueError("Snapshot resume_history must be a list.")
    history.append(
        {
            "resume_number": len(history) + 1,
            "previous_status": state.status.value,
            "failure": copy.deepcopy(state.failure),
        }
    )
    state.status = TournamentStatus.IN_PROGRESS
    state.failure = None
    state.completed = False
    state.winner_seat = None
    result["status"] = TournamentStatus.IN_PROGRESS.value
    result["completed_at"] = None
    result["winner"] = None
    result["placements"] = {}
    result["judge_evaluations"] = []
    sync_runtime_checkpoint(result, state)
