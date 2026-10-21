"""Deterministic replay of saved tournament actions through the engine."""

from task_3.pokermind.core.domain import ActionDecision, ActionType, TournamentState
from task_3.pokermind.engine import (
    advance_street,
    apply_action,
    create_tournament,
    start_hand,
)
from task_3.pokermind.results.document import (
    _player_stacks,
    _seat_map,
    _sync_hand_replay,
)


def replay_tournament(result: dict[str, object]) -> TournamentState:
    """Replay recorded actions through the engine without invoking any agent."""
    state = create_tournament(
        str(result["tournament_id"]),
        int(result["seed"]),
        int(result["initial_button"]),
    )
    hands = result["hands"]
    if not isinstance(hands, list):
        raise TypeError("Tournament result hands must be a list.")
    for expected_hand in hands:
        if not isinstance(expected_hand, dict):
            raise TypeError("Each recorded hand must be a dictionary.")
        hand = start_hand(state)
        if hand.hand_seed != expected_hand["hand_seed"]:
            raise AssertionError("Recorded hand seed does not match replay.")
        actual_blinds = {"small": hand.small_blind, "big": hand.big_blind}
        if actual_blinds != expected_hand["blinds"]:
            raise AssertionError("Recorded blinds do not match replay.")
        actual_positions = {
            "button": hand.button_seat,
            "small_blind": hand.small_blind_seat,
            "big_blind": hand.big_blind_seat,
            "preflop_first": hand.preflop_first_seat,
            "postflop_first": hand.postflop_first_seat,
        }
        if actual_positions != expected_hand["positions"]:
            raise AssertionError("Recorded positions do not match replay.")
        if _seat_map(hand.starting_stacks) != expected_hand["starting_stacks"]:
            raise AssertionError("Recorded starting stacks do not match replay.")
        if hand.forced_blinds != expected_hand["forced_blinds"]:
            raise AssertionError("Recorded forced blinds do not match replay.")
        actual_holes = {
            str(seat): [card.short_name() for card in player.hole_cards]
            for seat, player in sorted(state.players.items())
            if player.hole_cards
        }
        if actual_holes != expected_hand["hole_cards"]:
            raise AssertionError("Recorded hole cards do not match replay.")

        decisions = expected_hand.get("decisions", [])
        for recorded in decisions:
            if not isinstance(recorded, dict):
                raise TypeError("Each recorded decision must be a dictionary.")
            while not hand.completed and (
                not hand.pending_to_act or hand.street.value != recorded["street"]
            ):
                if not hand.round_complete:
                    raise AssertionError(
                        "Replay cannot reach the next recorded action."
                    )
                advance_street(state)
            executed = recorded.get("final_executed")
            if not isinstance(executed, dict):
                if recorded.get("api_failed") is not True:
                    raise ValueError(
                        "A replayable tournament contains an unexecuted decision "
                        "that was not an API failure."
                    )
                if _player_stacks(state) != recorded["stacks_after"]:
                    raise AssertionError("Failed decision changed recorded stacks.")
                if hand.pot != recorded["pot_after"]:
                    raise AssertionError("Failed decision changed the recorded pot.")
                continue
            actor = int(recorded["actor_seat"])
            if not hand.pending_to_act or hand.pending_to_act[0] != actor:
                raise AssertionError(
                    "Recorded actor does not match replay action order."
                )
            apply_action(
                state,
                actor,
                ActionDecision(
                    ActionType(str(executed["ACTION"])), int(executed["AMOUNT"])
                ),
            )
            if _player_stacks(state) != recorded["stacks_after"]:
                raise AssertionError("Recorded stacks do not match replay.")
            if hand.pot != recorded["pot_after"]:
                raise AssertionError("Recorded pot does not match replay.")

        while not hand.completed:
            if not hand.round_complete:
                raise AssertionError("Recorded hand ended before replay completed.")
            advance_street(state)
        replay_record: dict[str, object] = {}
        _sync_hand_replay(replay_record, hand)
        expected_actions = [
            {key: value for key, value in action.items() if key != "reason"}
            for action in expected_hand["public_actions"]
        ]
        if replay_record["public_actions"] != expected_actions:
            raise AssertionError("Recorded public actions do not match replay.")
        for field in (
            "board",
            "all_in_cap",
            "refunds",
            "all_in_final_contributions",
            "showdown_results",
            "winning_rank",
            "winners",
            "pot_awards",
            "odd_chip_order",
            "eliminations",
            "completed",
        ):
            if replay_record[field] != expected_hand[field]:
                raise AssertionError(f"Recorded {field} does not match replay.")
        if _player_stacks(state) != expected_hand["ending_stacks"]:
            raise AssertionError("Recorded ending stacks do not match replay.")

    if state.status.value != result["status"]:
        raise AssertionError("Recorded tournament status does not match replay.")
    replay_winner = (
        state.players[state.winner_seat].name.value
        if state.winner_seat is not None
        else None
    )
    if replay_winner != result["winner"]:
        raise AssertionError("Recorded tournament winner does not match replay.")
    return state
