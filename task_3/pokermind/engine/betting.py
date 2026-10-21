"""Betting-round validation and deterministic action transitions."""

from task_3.pokermind.core.domain import (
    ActionDecision,
    ActionType,
    LegalAction,
    PlayerState,
    Street,
    TournamentState,
)


def _seats_from(state: TournamentState, first_seat: int) -> list[int]:
    return [
        (first_seat + offset) % len(state.players)
        for offset in range(len(state.players))
    ]


def _can_act(player: PlayerState) -> bool:
    return (
        not player.eliminated
        and not player.folded
        and not player.all_in
        and player.stack > 0
    )


def initialize_betting_round(state: TournamentState, first_seat: int) -> None:
    """Initialize the ordered actor queue for the hand's current street."""
    hand = state.current_hand
    if hand is None:
        raise ValueError("Cannot initialize betting without a current hand.")
    if first_seat not in state.players:
        raise ValueError(f"Unknown physical seat {first_seat}.")

    if hand.street is Street.PREFLOP:
        hand.current_bet = max(
            player.street_contribution for player in state.players.values()
        )
    else:
        hand.current_bet = 0
    hand.last_full_raise_size = hand.big_blind
    hand.pending_to_act = [
        seat for seat in _seats_from(state, first_seat) if _can_act(state.players[seat])
    ]
    hand.round_complete = not hand.pending_to_act


def legal_actions(state: TournamentState, actor: int) -> list[LegalAction]:
    """Return the actor's exact deterministic legal-action description."""
    hand = state.current_hand
    if hand is None:
        return []
    if actor not in state.players:
        return []
    player = state.players[actor]
    if (
        not _can_act(player)
        or hand.round_complete
        or hand.uncontested_winner_seat is not None
        or not hand.pending_to_act
        or hand.pending_to_act[0] != actor
    ):
        return []

    if hand.all_in_resolution:
        if hand.all_in_cap is None:
            raise AssertionError("All-in resolution requires a contribution cap.")
        amount = min(hand.all_in_cap - player.hand_contribution, player.stack)
        return [
            LegalAction(ActionType.FOLD, amount=0),
            LegalAction(ActionType.CALL, amount=amount),
        ]

    to_call = max(0, hand.current_bet - player.street_contribution)
    actions: list[LegalAction] = []
    if to_call == 0:
        actions.append(LegalAction(ActionType.CHECK, amount=0))
    else:
        actions.extend(
            (
                LegalAction(ActionType.FOLD, amount=0),
                LegalAction(ActionType.CALL, amount=min(to_call, player.stack)),
            )
        )

    if player.stack > to_call:
        normal_minimum = to_call + hand.last_full_raise_size
        minimum = normal_minimum if player.stack >= normal_minimum else player.stack
        actions.append(
            LegalAction(
                ActionType.RAISE,
                min_amount=minimum,
                max_amount=player.stack,
            )
        )
    return actions


def validate_action(
    state: TournamentState, actor: int, decision: ActionDecision
) -> list[str]:
    """Return concrete validation errors without mutating poker state."""
    errors: list[str] = []
    hand = state.current_hand
    if hand is None:
        return ["No hand is active."]
    if (
        isinstance(actor, bool)
        or not isinstance(actor, int)
        or actor not in state.players
    ):
        return [f"Unknown physical seat {actor!r}."]
    if not hand.pending_to_act or hand.pending_to_act[0] != actor:
        errors.append("Actor is out of turn or has no pending action.")
    if not isinstance(decision, ActionDecision):
        return [*errors, "Decision must be an ActionDecision."]
    if not isinstance(decision.action, ActionType):
        errors.append("Action must be a valid ActionType.")
    if isinstance(decision.amount, bool) or not isinstance(decision.amount, int):
        errors.append("Amount must be a non-negative integer.")
    elif decision.amount < 0:
        errors.append("Amount must be a non-negative integer.")

    available = legal_actions(state, actor)
    matching = [action for action in available if action.action is decision.action]
    if isinstance(decision.action, ActionType) and not matching:
        errors.append(f"{decision.action.value} is not currently legal.")
    elif (
        matching
        and isinstance(decision.amount, int)
        and not isinstance(decision.amount, bool)
    ):
        legal = matching[0]
        if legal.amount is not None and decision.amount != legal.amount:
            errors.append(
                f"{decision.action.value} requires amount {legal.amount}, got {decision.amount}."
            )
        if legal.min_amount is not None and not (
            legal.min_amount <= decision.amount <= (legal.max_amount or 0)
        ):
            errors.append(
                f"RAISE amount must be between {legal.min_amount} and "
                f"{legal.max_amount}, got {decision.amount}."
            )
    return errors


def _transfer_to_pot(state: TournamentState, actor: int, amount: int) -> None:
    hand = state.current_hand
    if hand is None:
        raise ValueError("No hand is active.")
    player = state.players[actor]
    player.stack -= amount
    player.street_contribution += amount
    player.hand_contribution += amount
    hand.pot += amount
    player.all_in = player.stack == 0


def _record_public_action(
    state: TournamentState, actor: int, decision: ActionDecision
) -> None:
    hand = state.current_hand
    if hand is None:
        raise ValueError("No hand is active.")
    player = state.players[actor]
    statistics = state.public_stats[player.name]
    statistics["decisions"] = int(statistics["decisions"]) + 1
    count_key = {
        ActionType.FOLD: "folds",
        ActionType.CHECK: "checks",
        ActionType.CALL: "calls",
        ActionType.RAISE: "raises",
    }[decision.action]
    statistics[count_key] = int(statistics[count_key]) + 1
    if decision.action in {ActionType.CALL, ActionType.RAISE}:
        statistics["voluntary_chips"] = (
            int(statistics["voluntary_chips"]) + decision.amount
        )
        if player.all_in:
            statistics["all_ins"] = int(statistics["all_ins"]) + 1
    recent_actions = statistics["recent_actions"]
    if not isinstance(recent_actions, list):
        raise AssertionError("Recent public actions must be stored as a list.")
    recent_actions.append(
        {
            "hand_number": hand.hand_number,
            "street": hand.street.value,
            "action": decision.action.value,
            "amount": decision.amount,
        }
    )
    del recent_actions[:-5]


def _finish_action(state: TournamentState) -> None:
    hand = state.current_hand
    if hand is None:
        raise ValueError("No hand is active.")
    remaining = [
        player.seat
        for player in state.players.values()
        if not player.eliminated and not player.folded
    ]
    if len(remaining) == 1:
        hand.uncontested_winner_seat = remaining[0]
        hand.pending_to_act.clear()
        hand.round_complete = True
        return

    matched = all(
        player.street_contribution == hand.current_bet
        for player in state.players.values()
        if not player.eliminated and not player.folded and player.stack > 0
    )
    hand.round_complete = not hand.pending_to_act and matched
