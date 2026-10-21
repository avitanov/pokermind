"""Core deterministic value types and state for PokerMind."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


STARTING_STACK = 500
TOTAL_CHIPS = 1_500
PLAYER_MODEL_ID = "deepseek/deepseek-v4-flash"
JUDGE_MODEL_ID = "google/gemini-3-flash-preview"
PEEK_SEED_OFFSET = 7_919_191


class PlayerName(str, Enum):
    """The three fixed tournament players."""

    CONSERVATIVE = "Conservative"
    AGGRESSIVE = "Aggressive"
    ADAPTIVE = "Adaptive"


class Street(str, Enum):
    """The ordinary stages of a Hold'em hand."""

    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"
    SHOWDOWN = "showdown"


class ActionType(str, Enum):
    """Actions that a player agent may propose."""

    FOLD = "FOLD"
    CHECK = "CHECK"
    CALL = "CALL"
    RAISE = "RAISE"


class PokerDecision(BaseModel):
    """Strict structured output contract for one proposed poker action."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    action: ActionType = Field(alias="ACTION")
    amount: int = Field(alias="AMOUNT", ge=0, strict=True)
    reason: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=240, strict=True
        ),
    ] = Field(alias="REASON")


def empty_public_statistics() -> dict[str, object]:
    """Return an independent zeroed current-tournament statistics record."""
    return {
        "decisions": 0,
        "folds": 0,
        "checks": 0,
        "calls": 0,
        "raises": 0,
        "all_ins": 0,
        "voluntary_chips": 0,
        "recent_actions": [],
    }


class TournamentStatus(str, Enum):
    """Lifecycle status of one tournament run."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class Suit(str, Enum):
    """Card suits represented by their stable one-character codes."""

    CLUBS = "c"
    DIAMONDS = "d"
    HEARTS = "h"
    SPADES = "s"


@dataclass(frozen=True, slots=True)
class Card:
    """An immutable playing card with a rank from 2 through Ace."""

    rank: int
    suit: Suit

    def __post_init__(self) -> None:
        if isinstance(self.rank, bool) or not isinstance(self.rank, int):
            raise TypeError("Card rank must be an integer from 2 through 14.")
        if not 2 <= self.rank <= 14:
            raise ValueError("Card rank must be between 2 and 14.")
        if not isinstance(self.suit, Suit):
            raise TypeError("Card suit must be a Suit value.")

    @classmethod
    def parse(cls, value: str) -> "Card":
        """Parse a checked two-character card code such as ``As``."""
        if not isinstance(value, str):
            raise TypeError("Card code must be a string such as 'As'.")
        if len(value) != 2:
            raise ValueError(
                "Card code must contain exactly a rank and suit, such as 'As'."
            )

        rank_codes = {
            "2": 2,
            "3": 3,
            "4": 4,
            "5": 5,
            "6": 6,
            "7": 7,
            "8": 8,
            "9": 9,
            "T": 10,
            "J": 11,
            "Q": 12,
            "K": 13,
            "A": 14,
        }
        rank_code, suit_code = value
        if rank_code not in rank_codes:
            raise ValueError(
                f"Invalid card rank {rank_code!r}; use 2-9, T, J, Q, K, or A."
            )
        try:
            suit = Suit(suit_code)
        except ValueError as error:
            raise ValueError(
                f"Invalid card suit {suit_code!r}; use c, d, h, or s."
            ) from error
        return cls(rank=rank_codes[rank_code], suit=suit)

    def short_name(self) -> str:
        """Return the stable two-character JSON representation."""
        rank_code = str(self.rank) if self.rank < 10 else "TJQKA"[self.rank - 10]
        return f"{rank_code}{self.suit.value}"

    def __str__(self) -> str:
        return self.short_name()


@dataclass(slots=True)
class PlayerState:
    """Mutable tournament and current-hand state for one fixed seat."""

    seat: int
    name: PlayerName
    stack: int = STARTING_STACK
    eliminated: bool = False
    hole_cards: list[Card] = field(default_factory=list)
    folded: bool = False
    all_in: bool = False
    hand_contribution: int = 0
    street_contribution: int = 0


@dataclass(frozen=True, slots=True)
class LegalAction:
    """One exact action or inclusive raise range currently available."""

    action: ActionType
    amount: int | None = None
    min_amount: int | None = None
    max_amount: int | None = None


@dataclass(frozen=True, slots=True)
class ActionDecision:
    """A deterministic action proposal used by the poker engine."""

    action: ActionType
    amount: int


@dataclass(slots=True)
class HandState:
    """Complete deterministic state for the current hand."""

    hand_number: int
    street: Street
    small_blind: int
    big_blind: int
    button_seat: int
    small_blind_seat: int
    big_blind_seat: int
    preflop_first_seat: int
    postflop_first_seat: int
    starting_stacks: dict[int, int] = field(default_factory=dict)
    hand_seed: int | None = None
    deck: list[Card] = field(default_factory=list)
    pot: int = 0
    board: list[Card] = field(default_factory=list)
    forced_blinds: list[dict[str, int | str]] = field(default_factory=list)
    current_bet: int = 0
    last_full_raise_size: int = 0
    pending_to_act: list[int] = field(default_factory=list)
    round_complete: bool = False
    uncontested_winner_seat: int | None = None
    action_history: list[dict[str, int | str]] = field(default_factory=list)
    completed: bool = False
    winner_seats: list[int] = field(default_factory=list)
    pot_awards: dict[int, int] = field(default_factory=dict)
    odd_chip_order: list[int] = field(default_factory=list)
    showdown_results: dict[int, dict[str, object]] = field(default_factory=dict)
    winning_rank: tuple[int, ...] | None = None
    all_in_resolution: bool = False
    all_in_cap: int | None = None
    refund_events: list[dict[str, int | str]] = field(default_factory=list)
    all_in_final_contributions: dict[int, int] = field(default_factory=dict)
    eliminated_seats: list[int] = field(default_factory=list)


@dataclass(slots=True)
class TournamentState:
    """Tournament-local state that is never passed directly to an agent."""

    tournament_id: str
    seed: int
    players: dict[int, PlayerState]
    button_seat: int
    hand_number: int = 0
    current_hand: HandState | None = None
    public_stats: dict[PlayerName, dict[str, object]] = field(default_factory=dict)
    peek_available: bool = True
    peek_seed: int = 0
    adaptive_peek_observation: dict[str, int | str] | None = None
    status: TournamentStatus = TournamentStatus.IN_PROGRESS
    failure: dict[str, object] | None = None
    completed: bool = False
    winner_seat: int | None = None
    events: list[dict[str, object]] = field(default_factory=list)
    counters: dict[str, int] = field(
        default_factory=lambda: {
            "hands_completed": 0,
            "actions": 0,
            "api_failures": 0,
            "api_fallbacks": 0,
        }
    )
