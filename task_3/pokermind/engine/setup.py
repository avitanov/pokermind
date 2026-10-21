"""Tournament setup, positions, blinds, and shared engine invariants."""

from task_3.pokermind.core.domain import (
    STARTING_STACK,
    TOTAL_CHIPS,
    PEEK_SEED_OFFSET,
    LegalAction,
    PlayerName,
    PlayerState,
    TournamentState,
    empty_public_statistics,
)

BLIND_LEVELS = (
    (25, 50),
    (75, 100),
    (150, 200),
    (200, 300),
    (400, 700),
    (700, 1000),
    (1000, 1500),
)
SEAT_NAMES = (
    PlayerName.CONSERVATIVE,
    PlayerName.AGGRESSIVE,
    PlayerName.ADAPTIVE,
)
HAND_SEED_MULTIPLIER = 1_000_003
MAX_TOURNAMENT_HANDS = 100


class ActionValidationError(ValueError):
    """An action proposal failed deterministic poker validation."""

    def __init__(self, errors: list[str], legal_actions: list[LegalAction]) -> None:
        self.errors = errors
        self.legal_actions = legal_actions
        super().__init__("; ".join(errors))


class TournamentLimitError(RuntimeError):
    """The deterministic tournament exceeded its completed-hand ceiling."""

    def __init__(self, state: TournamentState) -> None:
        self.state = state
        super().__init__(
            f"Tournament reached the {MAX_TOURNAMENT_HANDS}-hand safety ceiling."
        )


def create_tournament(
    tournament_id: str, seed: int, initial_button_seat: int
) -> TournamentState:
    """Create fresh state for one isolated three-player tournament."""
    if not isinstance(tournament_id, str) or not tournament_id.strip():
        raise ValueError("Tournament ID must be a non-empty string.")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("Tournament seed must be an integer.")
    if (
        isinstance(initial_button_seat, bool)
        or not isinstance(initial_button_seat, int)
        or initial_button_seat not in range(len(SEAT_NAMES))
    ):
        raise ValueError("Initial button seat must be 0, 1, or 2.")

    players = {
        seat: PlayerState(seat=seat, name=name, stack=STARTING_STACK)
        for seat, name in enumerate(SEAT_NAMES)
    }
    public_stats = {name: empty_public_statistics() for name in SEAT_NAMES}
    return TournamentState(
        tournament_id=tournament_id,
        seed=seed,
        players=players,
        button_seat=initial_button_seat,
        public_stats=public_stats,
        peek_available=True,
        peek_seed=seed + PEEK_SEED_OFFSET,
        adaptive_peek_observation=None,
    )


def active_seats(state: TournamentState) -> list[int]:
    """Return active physical seats in stable seat order."""
    return [
        seat
        for seat, player in sorted(state.players.items())
        if not player.eliminated and player.stack > 0
    ]


def next_active_seat(state: TournamentState, seat: int) -> int:
    """Find the next active seat clockwise, skipping eliminated players."""
    if seat not in state.players:
        raise ValueError(f"Unknown physical seat {seat}.")
    for offset in range(1, len(state.players) + 1):
        candidate = (seat + offset) % len(state.players)
        player = state.players[candidate]
        if not player.eliminated and player.stack > 0:
            return candidate
    raise ValueError("No active player remains after the given seat.")


def positions_for_hand(state: TournamentState) -> dict[str, int]:
    """Calculate button, blinds, and first actors for the next hand."""
    seats = active_seats(state)
    if len(seats) not in (2, 3):
        raise ValueError("A hand requires exactly two or three active players.")
    if state.button_seat not in seats:
        raise ValueError("The button must be on an active seat before a hand starts.")

    button = state.button_seat
    if len(seats) == 2:
        small_blind = button
        big_blind = next_active_seat(state, button)
        preflop_first = button
        postflop_first = big_blind
    else:
        small_blind = next_active_seat(state, button)
        big_blind = next_active_seat(state, small_blind)
        preflop_first = next_active_seat(state, big_blind)
        postflop_first = next_active_seat(state, button)

    return {
        "button": button,
        "small_blind": small_blind,
        "big_blind": big_blind,
        "preflop_first": preflop_first,
        "postflop_first": postflop_first,
    }


def blind_for_hand(hand_number: int) -> tuple[int, int]:
    """Return the configured blinds for a one-based hand number."""
    if isinstance(hand_number, bool) or not isinstance(hand_number, int):
        raise TypeError("Hand number must be an integer.")
    if hand_number < 1:
        raise ValueError("Hand number must be at least 1.")
    level = min((hand_number - 1) // 2, len(BLIND_LEVELS) - 1)
    return BLIND_LEVELS[level]


def assert_chip_invariants(state: TournamentState) -> None:
    """Raise if forced-bet chip accounting is inconsistent."""
    hand = state.current_hand
    pot = hand.pot if hand is not None else 0
    chip_values = [
        pot,
        *(
            value
            for player in state.players.values()
            for value in (
                player.stack,
                player.hand_contribution,
                player.street_contribution,
            )
        ),
    ]
    if any(
        isinstance(value, bool) or not isinstance(value, int) for value in chip_values
    ):
        raise AssertionError("Stacks, contributions, and the pot must be integers.")
    if any(player.stack < 0 for player in state.players.values()):
        raise AssertionError("Player stacks cannot be negative.")
    if any(
        player.hand_contribution < 0 or player.street_contribution < 0
        for player in state.players.values()
    ):
        raise AssertionError("Player contributions cannot be negative.")
    if pot < 0:
        raise AssertionError("The pot cannot be negative.")
    if sum(player.stack for player in state.players.values()) + pot != TOTAL_CHIPS:
        raise AssertionError(
            f"Player stacks plus the pot must equal {TOTAL_CHIPS} chips."
        )
    if hand is not None:
        contributions = sum(
            player.hand_contribution for player in state.players.values()
        )
        if pot != contributions:
            raise AssertionError("The pot must equal all current hand contributions.")
        all_cards = [
            *hand.deck,
            *hand.board,
            *(card for player in state.players.values() for card in player.hole_cards),
        ]
        if len(all_cards) != len(set(all_cards)):
            raise AssertionError(
                "No card may appear twice in deterministic hand state."
            )
