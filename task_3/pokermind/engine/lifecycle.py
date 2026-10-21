"""Hand initialization, street progression, showdown, and pot awards."""

from task_3.pokermind.core.domain import (
    TOTAL_CHIPS,
    Card,
    HandState,
    Street,
    TournamentState,
    TournamentStatus,
)
from task_3.pokermind.engine.all_in import (
    _begin_all_in_resolution,
    _continue_all_in_resolution,
)
from task_3.pokermind.engine.betting import _seats_from, initialize_betting_round
from task_3.pokermind.engine.cards import Deck, evaluate_seven_cards
from task_3.pokermind.engine.setup import (
    HAND_SEED_MULTIPLIER,
    active_seats,
    assert_chip_invariants,
    blind_for_hand,
    next_active_seat,
    positions_for_hand,
)


def post_blind(
    state: TournamentState, seat: int, blind: int, position: str
) -> dict[str, int | str]:
    """Post one full or partial blind and record the exact stack change."""
    hand = state.current_hand
    if hand is None:
        raise ValueError("Cannot post a blind without a current hand.")
    if position not in {"small_blind", "big_blind"}:
        raise ValueError("Blind position must be 'small_blind' or 'big_blind'.")
    if seat not in state.players:
        raise ValueError(f"Unknown physical seat {seat}.")
    if isinstance(blind, bool) or not isinstance(blind, int) or blind < 0:
        raise ValueError("Blind amount must be a non-negative integer.")

    player = state.players[seat]
    stack_before = player.stack
    posted = min(blind, stack_before)
    player.stack -= posted
    player.hand_contribution += posted
    player.street_contribution += posted
    player.all_in = player.stack == 0
    hand.pot += posted

    record: dict[str, int | str] = {
        "seat": seat,
        "player": player.name.value,
        "position": position,
        "required": blind,
        "posted": posted,
        "stack_before": stack_before,
        "stack_after": player.stack,
    }
    hand.forced_blinds.append(record)
    assert_chip_invariants(state)
    return record


def setup_next_hand(state: TournamentState) -> HandState:
    """Initialize positions and post blinds without dealing or betting logic."""
    if state.current_hand is not None and not state.current_hand.completed:
        raise ValueError("Cannot set up a new hand while another hand is active.")
    assert_chip_invariants(state)

    positions = positions_for_hand(state)
    hand_number = state.hand_number + 1
    small_blind, big_blind = blind_for_hand(hand_number)
    for player in state.players.values():
        player.hole_cards.clear()
        player.folded = False
        player.all_in = False
        player.hand_contribution = 0
        player.street_contribution = 0
    # A peeked hole card is only valid for the hand it was revealed in; clear it
    # so a stale card is never re-served to Adaptive on later hands.
    state.adaptive_peek_observation = None

    hand = HandState(
        hand_number=hand_number,
        street=Street.PREFLOP,
        small_blind=small_blind,
        big_blind=big_blind,
        button_seat=positions["button"],
        small_blind_seat=positions["small_blind"],
        big_blind_seat=positions["big_blind"],
        preflop_first_seat=positions["preflop_first"],
        postflop_first_seat=positions["postflop_first"],
        starting_stacks={
            seat: player.stack for seat, player in sorted(state.players.items())
        },
    )
    state.hand_number = hand_number
    state.current_hand = hand
    post_blind(state, hand.small_blind_seat, small_blind, "small_blind")
    post_blind(state, hand.big_blind_seat, big_blind, "big_blind")
    initialize_betting_round(state, hand.preflop_first_seat)
    all_in_blinds = [
        player.hand_contribution
        for player in state.players.values()
        if player.all_in and player.hand_contribution > 0
    ]
    if all_in_blinds:
        _begin_all_in_resolution(
            state,
            min(all_in_blinds),
            hand.preflop_first_seat,
        )
    return hand


def hand_seed(tournament_seed: int, hand_number: int) -> int:
    """Derive a reproducible deck seed from tournament and hand numbers."""
    return tournament_seed * HAND_SEED_MULTIPLIER + hand_number


def _deal_from_hand(hand: HandState, count: int) -> list[Card]:
    if count > len(hand.deck):
        raise ValueError(
            f"Cannot deal {count} cards; only {len(hand.deck)} remain in the hand deck."
        )
    dealt = hand.deck[:count]
    del hand.deck[:count]
    return dealt


def start_hand(state: TournamentState) -> HandState:
    """Create a seeded deck, deal hole cards, and initialize preflop betting."""
    hand = setup_next_hand(state)
    hand.hand_seed = hand_seed(state.seed, hand.hand_number)
    hand.deck = list(Deck(hand.hand_seed).cards)
    for seat, player in state.players.items():
        if player.eliminated:
            continue
        state.players[seat].hole_cards = _deal_from_hand(hand, 2)
    assert_chip_invariants(state)
    if hand.all_in_resolution:
        _continue_all_in_resolution(state)
    return hand


def _reset_for_new_street(state: TournamentState) -> None:
    hand = state.current_hand
    if hand is None:
        raise ValueError("No hand is active.")
    for player in state.players.values():
        player.street_contribution = 0
    hand.uncontested_winner_seat = None
    initialize_betting_round(state, hand.postflop_first_seat)


def advance_street(state: TournamentState) -> Street:
    """Advance a completed normal betting round and deal required board cards."""
    hand = state.current_hand
    if hand is None:
        raise ValueError("No hand is active.")
    if hand.completed:
        raise ValueError("Cannot advance a completed hand.")
    if not hand.round_complete:
        raise ValueError("Cannot advance before the betting round is complete.")
    if hand.uncontested_winner_seat is not None:
        raise ValueError("An uncontested hand must be awarded instead of advanced.")
    if any(player.all_in for player in state.players.values() if not player.folded):
        raise ValueError("All-in hands require the Step 6 resolution path.")

    if hand.street is Street.PREFLOP:
        hand.street = Street.FLOP
        hand.board.extend(_deal_from_hand(hand, 3))
        _reset_for_new_street(state)
    elif hand.street is Street.FLOP:
        hand.street = Street.TURN
        hand.board.extend(_deal_from_hand(hand, 1))
        _reset_for_new_street(state)
    elif hand.street is Street.TURN:
        hand.street = Street.RIVER
        hand.board.extend(_deal_from_hand(hand, 1))
        _reset_for_new_street(state)
    elif hand.street is Street.RIVER:
        hand.street = Street.SHOWDOWN
        resolve_showdown(state)
    else:
        raise ValueError("Cannot advance beyond showdown.")
    assert_chip_invariants(state)
    return hand.street


def _award_pot(state: TournamentState, winners: list[int]) -> None:
    hand = state.current_hand
    if hand is None:
        raise ValueError("No hand is active.")
    if hand.completed:
        raise ValueError("A completed hand cannot award its pot again.")
    if not winners:
        raise ValueError("At least one winner is required to award the pot.")

    pot = hand.pot
    share, remainder = divmod(pot, len(winners))
    awards = {seat: share for seat in winners}
    winner_set = set(winners)
    order = [
        seat
        for seat in _seats_from(state, (hand.button_seat + 1) % len(state.players))
        if seat in winner_set
    ]
    odd_chip_order = order[:remainder]
    for seat in odd_chip_order:
        awards[seat] += 1
    for seat, amount in awards.items():
        state.players[seat].stack += amount

    hand.winner_seats = winners
    hand.pot_awards = awards
    hand.odd_chip_order = odd_chip_order
    hand.pot = 0
    hand.pending_to_act.clear()
    hand.round_complete = True
    hand.completed = True
    for player in state.players.values():
        player.hand_contribution = 0
        player.street_contribution = 0
    assert_chip_invariants(state)
    hand.eliminated_seats = []
    for player in state.players.values():
        if player.stack == 0:
            player.eliminated = True
            hand.eliminated_seats.append(player.seat)
    survivors = active_seats(state)
    if len(survivors) == 1:
        winner = survivors[0]
        if state.players[winner].stack != TOTAL_CHIPS:
            raise AssertionError(
                f"The tournament winner must hold all {TOTAL_CHIPS} chips."
            )
        state.completed = True
        state.status = TournamentStatus.COMPLETED
        state.winner_seat = winner
        state.button_seat = winner
    else:
        rotate_button(state)


def complete_uncontested_hand(state: TournamentState) -> int:
    """Award the pot immediately when every opponent has folded."""
    hand = state.current_hand
    if hand is None:
        raise ValueError("No hand is active.")
    if hand.completed:
        raise ValueError("A completed hand cannot be completed twice.")
    winner = hand.uncontested_winner_seat
    if winner is None:
        raise ValueError("The hand does not have an uncontested winner.")
    _award_pot(state, [winner])
    return winner


def resolve_showdown(state: TournamentState) -> list[int]:
    """Evaluate eligible hands and award the full pot deterministically."""
    hand = state.current_hand
    if hand is None:
        raise ValueError("No hand is active.")
    if hand.completed:
        raise ValueError("A completed hand cannot be completed twice.")
    if len(hand.board) != 5:
        raise ValueError("Showdown requires exactly five community cards.")

    eligible = [
        player
        for player in state.players.values()
        if not player.eliminated and not player.folded
    ]
    if len(eligible) < 2:
        raise ValueError("Showdown requires at least two eligible players.")

    ranks: dict[int, tuple[int, ...]] = {}
    for player in eligible:
        rank, category = evaluate_seven_cards([*player.hole_cards, *hand.board])
        ranks[player.seat] = rank
        hand.showdown_results[player.seat] = {
            "rank": rank,
            "category": category,
        }
    winning_rank = max(ranks.values())
    winners = [seat for seat, rank in ranks.items() if rank == winning_rank]
    hand.winning_rank = winning_rank
    _award_pot(state, winners)
    return winners


def rotate_button(state: TournamentState) -> int:
    """Move the button to the next seat that still has chips."""
    state.button_seat = next_active_seat(state, state.button_seat)
    return state.button_seat
