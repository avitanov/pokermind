"""Simplified all-in cap, refund, and board-runout behavior."""

from task_3.pokermind.core.domain import (
    ActionDecision,
    ActionType,
    Street,
    TournamentState,
)
from task_3.pokermind.engine.betting import (
    _can_act,
    _finish_action,
    _record_public_action,
    _seats_from,
    _transfer_to_pot,
    legal_actions,
    validate_action,
)
from task_3.pokermind.engine.setup import ActionValidationError, assert_chip_invariants


def _refund_above_cap(state: TournamentState) -> None:
    hand = state.current_hand
    if hand is None or hand.all_in_cap is None:
        raise ValueError("Cannot refund without an active all-in cap.")
    for player in state.players.values():
        if player.folded or player.hand_contribution <= hand.all_in_cap:
            continue
        excess = player.hand_contribution - hand.all_in_cap
        street_refund = min(excess, player.street_contribution)
        player.hand_contribution -= excess
        player.street_contribution -= street_refund
        player.stack += excess
        player.all_in = player.stack == 0
        hand.pot -= excess
        hand.refund_events.append(
            {
                "seat": player.seat,
                "player": player.name.value,
                "amount": excess,
                "street_refund": street_refund,
                "cap": hand.all_in_cap,
            }
        )
    assert_chip_invariants(state)


def _unsettled_all_in_seats(state: TournamentState, first_seat: int) -> list[int]:
    hand = state.current_hand
    if hand is None or hand.all_in_cap is None:
        raise ValueError("Cannot find unsettled players without an all-in cap.")
    return [
        seat
        for seat in _seats_from(state, first_seat)
        if not state.players[seat].eliminated
        and not state.players[seat].folded
        and not state.players[seat].all_in
        and state.players[seat].stack > 0
        and state.players[seat].hand_contribution < hand.all_in_cap
    ]


def _run_out_board(state: TournamentState) -> None:
    from task_3.pokermind.engine.lifecycle import _deal_from_hand, resolve_showdown

    hand = state.current_hand
    if hand is None:
        raise ValueError("No hand is active.")
    missing = 5 - len(hand.board)
    if missing < 0:
        raise ValueError("The board cannot contain more than five cards.")
    hand.board.extend(_deal_from_hand(hand, missing))
    hand.street = Street.SHOWDOWN
    resolve_showdown(state)


def _continue_all_in_resolution(state: TournamentState) -> None:
    from task_3.pokermind.engine.lifecycle import complete_uncontested_hand

    hand = state.current_hand
    if hand is None or not hand.all_in_resolution or hand.all_in_cap is None:
        raise ValueError("No all-in resolution is active.")
    remaining = [
        player
        for player in state.players.values()
        if not player.eliminated and not player.folded
    ]
    if len(remaining) == 1:
        hand.uncontested_winner_seat = remaining[0].seat
        complete_uncontested_hand(state)
        return
    if hand.pending_to_act:
        return
    if not all(player.hand_contribution == hand.all_in_cap for player in remaining):
        raise AssertionError(
            "All active contributions must match the final all-in cap."
        )
    if not hand.deck:
        hand.round_complete = True
        return
    hand.all_in_final_contributions = {
        player.seat: player.hand_contribution for player in remaining
    }
    hand.round_complete = True
    _run_out_board(state)


def _begin_all_in_resolution(state: TournamentState, cap: int, first_seat: int) -> None:
    hand = state.current_hand
    if hand is None:
        raise ValueError("No hand is active.")
    hand.all_in_resolution = True
    hand.all_in_cap = cap
    hand.current_bet = cap
    hand.round_complete = False
    _refund_above_cap(state)
    hand.pending_to_act = _unsettled_all_in_seats(state, first_seat)
    _continue_all_in_resolution(state)


def _apply_all_in_action(
    state: TournamentState, actor: int, decision: ActionDecision
) -> None:
    hand = state.current_hand
    if hand is None or hand.all_in_cap is None:
        raise ValueError("No all-in resolution is active.")
    player = state.players[actor]
    if decision.action is ActionType.FOLD:
        player.folded = True
    else:
        _transfer_to_pot(state, actor, decision.amount)
        if player.hand_contribution < hand.all_in_cap:
            hand.all_in_cap = player.hand_contribution
            hand.current_bet = hand.all_in_cap
            _refund_above_cap(state)
    hand.pending_to_act.pop(0)
    hand.pending_to_act = [
        seat
        for seat in hand.pending_to_act
        if not state.players[seat].folded
        and state.players[seat].hand_contribution < hand.all_in_cap
    ]


def apply_action(state: TournamentState, actor: int, decision: ActionDecision) -> None:
    """Validate and apply exactly one legal poker action."""
    from task_3.pokermind.engine.lifecycle import complete_uncontested_hand

    errors = validate_action(state, actor, decision)
    if errors:
        raise ActionValidationError(errors, legal_actions(state, actor))

    hand = state.current_hand
    if hand is None:
        raise ValueError("No hand is active.")
    player = state.players[actor]
    if hand.all_in_resolution:
        _apply_all_in_action(state, actor, decision)
    elif decision.action is ActionType.FOLD:
        player.folded = True
        hand.pending_to_act.pop(0)
    elif decision.action is ActionType.CHECK:
        hand.pending_to_act.pop(0)
    elif decision.action is ActionType.CALL:
        _transfer_to_pot(state, actor, decision.amount)
        hand.pending_to_act.pop(0)
    else:
        previous_bet = hand.current_bet
        _transfer_to_pot(state, actor, decision.amount)
        hand.current_bet = player.street_contribution
        raise_increment = hand.current_bet - previous_bet
        if raise_increment >= hand.last_full_raise_size:
            hand.last_full_raise_size = raise_increment
        next_seat = (actor + 1) % len(state.players)
        hand.pending_to_act = [
            seat
            for seat in _seats_from(state, next_seat)
            if seat != actor and _can_act(state.players[seat])
        ]

    hand.action_history.append(
        {
            "seat": actor,
            "player": player.name.value,
            "street": hand.street.value,
            "action": decision.action.value,
            "amount": decision.amount,
        }
    )
    _record_public_action(state, actor, decision)
    if (
        not hand.all_in_resolution
        and player.all_in
        and decision.action
        in {
            ActionType.CALL,
            ActionType.RAISE,
        }
    ):
        _begin_all_in_resolution(
            state,
            player.hand_contribution,
            (actor + 1) % len(state.players),
        )
    elif hand.all_in_resolution:
        _continue_all_in_resolution(state)
    else:
        _finish_action(state)
    assert_chip_invariants(state)
    if hand.uncontested_winner_seat is not None and not hand.completed:
        complete_uncontested_hand(state)
