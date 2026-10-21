# `core/` — shared domain vocabulary for PokerMind

This subpackage defines the deterministic value types, enums, constants, and state
containers that every other PokerMind subpackage imports. It is the single source of
truth for the poker card/deck primitives, the structured decision contract exchanged
with the LLM agents, and the mutable dataclasses that model player, hand, and
tournament state. It contains only data definitions and validation — no game logic.

All symbols live in `domain.py`; `__init__.py` is a docstring-only marker module.

## Files

### `domain.py` — constants, enums, data types, and functions

#### Constants
- `STARTING_STACK = 500` — chips each player begins the tournament with; default value of `PlayerState.stack`.
- `TOTAL_CHIPS = 1_500` — total chips in play (3 players x 500).
- `PLAYER_MODEL_ID = "deepseek/deepseek-v4-flash"` — model ID used for the poker player agents.
- `JUDGE_MODEL_ID = "google/gemini-3-flash-preview"` — model ID used for the judge/evaluation agent.
- `PEEK_SEED_OFFSET = 7_919_191` — offset added when deriving the deterministic seed for the Adaptive player's "peek" observation.

#### Enums
All enums subclass `str, Enum`, so their members compare equal to their string values.

- `PlayerName` — the three fixed tournament players: `CONSERVATIVE = "Conservative"`, `AGGRESSIVE = "Aggressive"`, `ADAPTIVE = "Adaptive"`.
- `Street` — stages of a Hold'em hand: `PREFLOP = "preflop"`, `FLOP = "flop"`, `TURN = "turn"`, `RIVER = "river"`, `SHOWDOWN = "showdown"`.
- `ActionType` — actions a player agent may propose: `FOLD = "FOLD"`, `CHECK = "CHECK"`, `CALL = "CALL"`, `RAISE = "RAISE"`.
- `TournamentStatus` — lifecycle status of a tournament run: `IN_PROGRESS = "in_progress"`, `COMPLETED = "completed"`, `FAILED = "failed"`.
- `Suit` — card suits by stable one-character code: `CLUBS = "c"`, `DIAMONDS = "d"`, `HEARTS = "h"`, `SPADES = "s"`.

#### Data types

##### `PokerDecision` (pydantic `BaseModel`)
Strict structured-output contract for one proposed poker action. `model_config` uses
`populate_by_name=True` (fields can be set by name or alias) and `extra="forbid"`
(rejects unknown keys). Fields (each carries an uppercase alias for the JSON contract):
- `action: ActionType` — alias `ACTION`; the proposed action.
- `amount: int` — alias `AMOUNT`; constrained `ge=0`, `strict=True` (no coercion); chip amount for the action.
- `reason: str` — alias `REASON`; whitespace-stripped, `min_length=1`, `max_length=240`, `strict=True`; free-text justification.

##### `Card` (frozen, slotted dataclass)
An immutable playing card with rank 2 through 14 (Ace).
- `rank: int` — 2..14; validated in `__post_init__` (rejects `bool`, non-`int`, and out-of-range values).
- `suit: Suit` — must be a `Suit` value (validated in `__post_init__`).
- `Card.parse(value: str) -> "Card"` — classmethod; parses a two-char code like `"As"` (ranks `2`-`9`, `T`, `J`, `Q`, `K`, `A` plus a suit code), raising `TypeError`/`ValueError` on malformed input.
- `short_name() -> str` — the stable two-character JSON representation (e.g. `"As"`, `"Th"`).
- `__str__` — delegates to `short_name()`.

##### `PlayerState` (slotted dataclass)
Mutable tournament and current-hand state for one fixed seat.
- `seat: int` — seat index.
- `name: PlayerName` — which fixed player occupies the seat.
- `stack: int = STARTING_STACK` — current chip stack.
- `eliminated: bool = False` — whether the player is out of the tournament.
- `hole_cards: list[Card]` — the player's private cards (default empty).
- `folded: bool = False` — folded in the current hand.
- `all_in: bool = False` — all-in in the current hand.
- `hand_contribution: int = 0` — chips contributed to the pot this hand.
- `street_contribution: int = 0` — chips contributed on the current street.

##### `LegalAction` (frozen, slotted dataclass)
One exact action or inclusive raise range currently available to a player.
- `action: ActionType` — the available action.
- `amount: int | None = None` — exact amount for a fixed action (e.g. call amount).
- `min_amount: int | None = None` — inclusive lower bound for a raise range.
- `max_amount: int | None = None` — inclusive upper bound for a raise range.

##### `ActionDecision` (frozen, slotted dataclass)
A deterministic action proposal consumed by the poker engine.
- `action: ActionType` — the chosen action.
- `amount: int` — the chip amount for the action.

##### `HandState` (slotted dataclass)
Complete deterministic state for the current hand.
- `hand_number: int` — index of the hand within the tournament.
- `street: Street` — current street.
- `small_blind: int` — small blind size.
- `big_blind: int` — big blind size.
- `button_seat: int` — dealer button seat.
- `small_blind_seat: int` — seat posting the small blind.
- `big_blind_seat: int` — seat posting the big blind.
- `preflop_first_seat: int` — first seat to act preflop.
- `postflop_first_seat: int` — first seat to act on flop/turn/river.
- `starting_stacks: dict[int, int]` — seat -> stack at hand start (default empty).
- `hand_seed: int | None = None` — deterministic seed for this hand's deck.
- `deck: list[Card]` — the shuffled deck (default empty).
- `pot: int = 0` — total chips in the pot.
- `board: list[Card]` — community cards (default empty).
- `forced_blinds: list[dict[str, int | str]]` — record of forced blind postings (default empty).
- `current_bet: int = 0` — amount to match on the current street.
- `last_full_raise_size: int = 0` — size of the last full raise (for min-raise rules).
- `pending_to_act: list[int]` — seats still owed action this street (default empty).
- `round_complete: bool = False` — whether the current betting round is finished.
- `uncontested_winner_seat: int | None = None` — seat winning by everyone else folding.
- `action_history: list[dict[str, int | str]]` — ordered log of actions taken (default empty).
- `completed: bool = False` — whether the hand is finished.
- `winner_seats: list[int]` — seats that won the hand (default empty).
- `pot_awards: dict[int, int]` — seat -> chips awarded (default empty).
- `odd_chip_order: list[int]` — tie-break order for distributing an odd chip (default empty).
- `showdown_results: dict[int, dict[str, object]]` — seat -> showdown detail (default empty).
- `winning_rank: tuple[int, ...] | None = None` — evaluated rank tuple of the winning hand.
- `all_in_resolution: bool = False` — whether the hand is being resolved via all-in runout.
- `all_in_cap: int | None = None` — chip cap when an all-in caps contributions.
- `refund_events: list[dict[str, int | str]]` — uncalled-bet refund records (default empty).
- `all_in_final_contributions: dict[int, int]` — seat -> final contribution in an all-in hand (default empty).
- `eliminated_seats: list[int]` — seats eliminated by this hand (default empty).

##### `TournamentState` (slotted dataclass)
Tournament-local state that is never passed directly to an agent.
- `tournament_id: str` — unique tournament identifier.
- `seed: int` — master RNG seed for the tournament.
- `players: dict[int, PlayerState]` — seat -> player state.
- `button_seat: int` — current dealer button seat.
- `hand_number: int = 0` — number of hands played so far.
- `current_hand: HandState | None = None` — the in-progress hand, if any.
- `public_stats: dict[PlayerName, dict[str, object]]` — per-player public statistics (default empty; see `empty_public_statistics`).
- `peek_available: bool = True` — whether the Adaptive player's peek is still usable.
- `peek_seed: int = 0` — seed used to derive the peek observation.
- `adaptive_peek_observation: dict[str, int | str] | None = None` — the recorded peek observation, if taken.
- `status: TournamentStatus = TournamentStatus.IN_PROGRESS` — lifecycle status.
- `failure: dict[str, object] | None = None` — failure detail when `status` is `FAILED`.
- `completed: bool = False` — whether the tournament has finished.
- `winner_seat: int | None = None` — winning seat once completed.
- `events: list[dict[str, object]]` — ordered event log (default empty).
- `counters: dict[str, int]` — running counters, defaulting to `{"hands_completed": 0, "actions": 0, "api_failures": 0, "api_fallbacks": 0}`.

#### Functions
- `empty_public_statistics() -> dict[str, object]` — returns a fresh, independent zeroed statistics record with keys `decisions`, `folds`, `checks`, `calls`, `raises`, `all_ins`, `voluntary_chips` (all `0`) and `recent_actions` (empty list). Used to initialize each player's entry in `TournamentState.public_stats`.

### `__init__.py` — docstring-only marker module
No exports; every subpackage imports directly from `domain.py`.

## How it fits together
Every other PokerMind subpackage (the `engine/`, `agents/`, `evaluation/`,
`experiment/`, and `observability/` packages) imports these types as the common
vocabulary for cards, actions, decisions, and tournament/hand/player state. This
module holds no game logic: it defines the data shapes, their defaults, and the
validation rules (`Card.__post_init__`, `Card.parse`, and the `PokerDecision`
pydantic constraints) — the behavior that acts on this state lives elsewhere.
