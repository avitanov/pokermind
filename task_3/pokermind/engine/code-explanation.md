# `engine/` — deterministic three-player No-Limit Hold'em rules engine

This subpackage implements the pure, reproducible poker rules for PokerMind: seeded shuffling and hand evaluation, tournament/position/blind setup, betting-round validation and action transitions, a simplified all-in resolution path, and hand lifecycle (deal, street progression, showdown, pot award). It contains **no LLM logic** — agents elsewhere decide actions, then call into this engine to validate and apply them. Everything operates on the shared mutable dataclasses `TournamentState`, `HandState`, and `PlayerState` (from `task_3.pokermind.core.domain`), plus value types `Card`, `ActionDecision`, and `LegalAction`. Determinism is enforced by seeded RNG and a repeatedly asserted 1500-chip conservation invariant (`TOTAL_CHIPS`).

## Files

### `cards.py` — seeded deck and seven-card hand evaluation
- `Deck(seed: int)` — a 52-card deck built in fixed order (suits × ranks 2–14) then shuffled by an isolated `random.Random(seed)`, so a given seed always yields the same order.
  - `.cards -> tuple[Card, ...]` — property returning the currently undealt cards in deal order (snapshot copy).
  - `.deal(count: int) -> list[Card]` — **mutates the deck**, removing and returning the top `count` cards. Raises `TypeError` if `count` is not an int (bools rejected), `ValueError` if negative or more than remaining.
- `evaluate_seven_cards(cards: Sequence[Card]) -> tuple[HandRank, str]` — pure; picks the best 5-card combo out of 7 and returns a lexicographically comparable rank tuple plus a category name (e.g. `"flush"`). Raises `ValueError` unless exactly 7 distinct cards, `TypeError` if any item is not a `Card`. Higher tuples beat lower ones.
- `HandRank` — type alias `tuple[int, ...]`; first element is the category index (0 high card … 9 royal flush), followed by tie-break kickers.
- `CATEGORY_NAMES` — tuple of the 10 category strings, indexed by the rank tuple's first element.
- `_straight_high(ranks)` (private) — returns the high card of a straight (handles the wheel A-2-3-4-5 → 5) or `None`. Used by the five-card evaluator.
- `_evaluate_five_cards(cards)` (private) — core five-card ranker producing a `HandRank`.

### `setup.py` — tournament creation, positions, blinds, and the chip invariant
- `create_tournament(tournament_id: str, seed: int, initial_button_seat: int) -> TournamentState` — builds fresh state: three seated players at `STARTING_STACK`, empty public stats, peek enabled with `peek_seed = seed + PEEK_SEED_OFFSET`. Validates id (non-empty str), seed (int, no bool), and button seat (0–2).
- `active_seats(state) -> list[int]` — pure; seats (sorted) that are not eliminated and have `stack > 0`.
- `next_active_seat(state, seat) -> int` — pure; next active seat clockwise, wrapping around, skipping eliminated/empty. Raises `ValueError` on unknown seat or if none remain.
- `positions_for_hand(state) -> dict[str, int]` — pure; computes `button`, `small_blind`, `big_blind`, `preflop_first`, `postflop_first`. Handles heads-up (2 players: button is small blind and acts first preflop) vs 3-handed. Raises if not 2–3 active players or the button is not on an active seat.
- `blind_for_hand(hand_number: int) -> tuple[int, int]` — pure; looks up `BLIND_LEVELS`, escalating every 2 hands (`(hand_number - 1) // 2`), capped at the last level. Raises on non-int or `< 1`.
- `assert_chip_invariants(state) -> None` — **the central consistency check**; raises `AssertionError` if any stack/contribution/pot is non-int or negative, if stacks + pot ≠ `TOTAL_CHIPS`, if pot ≠ sum of hand contributions, or if any card appears twice across deck/board/hole cards. Called after nearly every mutation.
- `ActionValidationError(ValueError)` — raised when a proposed action fails validation; carries `.errors: list[str]` and `.legal_actions: list[LegalAction]`.
- `TournamentLimitError(RuntimeError)` — carries `.state`; signals the `MAX_TOURNAMENT_HANDS` (100) safety ceiling (raised by callers outside this folder).
- Constants: `BLIND_LEVELS` (7 escalating tiers up to 1000/1500), `SEAT_NAMES` (CONSERVATIVE, AGGRESSIVE, ADAPTIVE), `HAND_SEED_MULTIPLIER` (1_000_003), `MAX_TOURNAMENT_HANDS` (100).

### `betting.py` — betting-round validation and normal action transitions
- `initialize_betting_round(state, first_seat: int) -> None` — **mutates the current hand**: sets `current_bet` (preflop = max street contribution i.e. the big blind, else 0), resets `last_full_raise_size` to the big blind, builds the ordered `pending_to_act` queue starting at `first_seat` (only actors who can act), and sets `round_complete` if the queue is empty. Raises if no current hand or unknown seat.
- `legal_actions(state, actor: int) -> list[LegalAction]` — pure; returns the exact legal actions for `actor`, or `[]` if it is not their turn / they cannot act / the round is over. During all-in resolution returns only FOLD and a fixed-amount CALL up to the cap. Otherwise returns CHECK (when nothing to call) or FOLD+CALL, plus RAISE with `min_amount`/`max_amount` when the stack allows (min = to-call + last full raise, or all-in if short).
- `validate_action(state, actor, decision: ActionDecision) -> list[str]` — pure; returns a list of human-readable error strings (empty = valid). Checks active hand, valid/known seat, turn order, decision type, non-negative int amount, action legality, and exact/ranged amount match against `legal_actions`. **Does not mutate state.**
- `_transfer_to_pot(state, actor, amount)` (private) — moves chips from stack into pot: decrements `stack`, increments `street_contribution`/`hand_contribution`/`pot`, and sets `all_in` when stack hits 0.
- `_record_public_action(state, actor, decision)` (private) — updates `public_stats` for the player (decision/fold/check/call/raise counts, voluntary chips, all-in count) and appends to a rolling last-5 `recent_actions` list.
- `_finish_action(state)` (private) — after an action, if only one non-folded player remains sets `uncontested_winner_seat` and ends the round; otherwise sets `round_complete` when the queue is empty and all live players have matched `current_bet`.
- `_seats_from(state, first_seat)` (private) — ordered list of all seats starting at `first_seat`, wrapping.
- `_can_act(player)` (private) — true when a player is not eliminated/folded/all-in and has chips.

### `all_in.py` — simplified all-in cap, refunds, and board runout
- `apply_action(state, actor, decision) -> None` — **the primary mutating entry point.** Validates first (raises `ActionValidationError` on failure), then applies exactly one action: dispatches to all-in handling if a resolution is active, else applies FOLD/CHECK/CALL/RAISE (RAISE recomputes `current_bet` and `last_full_raise_size` and rebuilds the actor queue). Appends to `action_history`, records public stats, then either **begins** all-in resolution (if the actor just went all-in via CALL/RAISE), **continues** an active resolution, or calls `_finish_action`. Asserts chip invariants and auto-completes an uncontested hand at the end.
- `_begin_all_in_resolution(state, cap, first_seat)` (private) — sets `all_in_resolution`, `all_in_cap`, and `current_bet` to the cap, refunds chips above the cap, seeds the unsettled-actor queue, then continues resolution. Called from `apply_action` and from `setup_next_hand`/`start_hand` when blinds force an all-in.
- `_continue_all_in_resolution(state)` (private) — drives resolution to conclusion: if one player remains, awards uncontested; if actors still pending, returns; otherwise verifies all contributions equal the cap, records `all_in_final_contributions`, marks the round complete, and runs out the board.
- `_apply_all_in_action(state, actor, decision)` (private) — applies a FOLD or capped CALL during resolution; if a call lands below the cap it lowers the cap and re-refunds, then prunes the pending queue.
- `_refund_above_cap(state)` (private) — returns each non-folded player's contribution above `all_in_cap` back to their stack (adjusting pot and street contribution), logging each to `refund_events`; asserts invariants after.
- `_unsettled_all_in_seats(state, first_seat)` (private) — seats still owing chips up to the cap (not eliminated/folded/all-in, still have chips, below cap).
- `_run_out_board(state)` (private) — deals the remaining community cards to reach 5, sets street to SHOWDOWN, and resolves showdown. Imports `lifecycle` lazily to avoid a circular import.

### `lifecycle.py` — hand setup, dealing, street progression, showdown, pot award
- `post_blind(state, seat, blind, position) -> dict` — **mutates state**: posts a full or partial (short-stack) blind, moving chips into the pot, sets `all_in` if the stack is exhausted, appends a record to `forced_blinds`, and returns it. Validates position (`"small_blind"`/`"big_blind"`), seat, and non-negative int blind; asserts invariants.
- `setup_next_hand(state) -> HandState` — resets per-player hand fields, computes positions and escalating blinds, creates a new `HandState` (recording `starting_stacks`), assigns it to `state.current_hand`, increments `state.hand_number`, posts both blinds, initializes preflop betting, and begins all-in resolution if a blind put someone all-in. Does **not** deal cards. Raises if a prior hand is still active.
- `hand_seed(tournament_seed, hand_number) -> int` — pure; `tournament_seed * HAND_SEED_MULTIPLIER + hand_number`, giving each hand a reproducible independent deck seed.
- `start_hand(state) -> HandState` — calls `setup_next_hand`, then builds the seeded `Deck`, stores it as `hand.deck`, deals 2 hole cards to each non-eliminated player, and continues any pending all-in resolution. The full "begin a hand" entry point.
- `advance_street(state) -> Street` — **mutates state**: for a completed, contested, non-all-in normal round, advances PREFLOP→FLOP (deal 3), FLOP→TURN (deal 1), TURN→RIVER (deal 1), or RIVER→SHOWDOWN (resolve). Raises if the hand is completed, the round is not complete, an uncontested winner exists, or anyone live is all-in (those go through the all-in path).
- `complete_uncontested_hand(state) -> int` — awards the whole pot to `uncontested_winner_seat` and returns it. Raises if there is no such winner or the hand is already completed.
- `resolve_showdown(state) -> list[int]` — evaluates each eligible (non-folded, non-eliminated) player's best 7-card hand, records `showdown_results`, finds the max rank, and awards the pot to all seats tied for it. Requires exactly 5 board cards and ≥2 eligible players.
- `rotate_button(state) -> int` — **mutates** `button_seat` to the next chip-holding seat and returns it.
- `_award_pot(state, winners)` (private) — splits the pot among winners with the odd chip going to the earliest winner left of the button; zeroes the pot and contributions, marks the hand completed, flags newly eliminated players (`eliminated_seats`), and either finishes the tournament (single survivor holds all `TOTAL_CHIPS`) or rotates the button. Asserts invariants.
- `_reset_for_new_street(state)` (private) — zeroes street contributions, clears any uncontested winner, and reinitializes betting from the postflop first actor.
- `_deal_from_hand(hand, count)` (private) — pops and returns `count` cards off the front of `hand.deck`; raises if too few remain.

## How it fits together

A caller (the tournament driver / agents layer, outside this folder) uses the package roughly in this order:

1. `create_tournament(...)` → a fresh `TournamentState` (each player at 500, `TOTAL_CHIPS` = 1500).
2. `start_hand(state)` per hand — internally runs `setup_next_hand` (positions via `positions_for_hand`, blinds via `blind_for_hand`, `post_blind` twice, `initialize_betting_round`) then builds a seeded `Deck` (`hand_seed` → `Deck`) and deals hole cards. All mutation lands on `state.current_hand` (a `HandState`) and `state.players` (`PlayerState`s).
3. For each decision, the agent proposes an `ActionDecision`; the caller (or `apply_action` itself) uses `legal_actions`/`validate_action` to check it, then `apply_action(state, actor, decision)` mutates the hand — moving chips to the pot, updating the `pending_to_act` queue, recording history and public stats, and deciding whether the round is complete, uncontested, or entering all-in resolution.
4. When `round_complete` and the hand is contested with no live all-ins, `advance_street` deals the next board cards; at RIVER it calls `resolve_showdown`. All-in situations instead run out the board automatically inside the `all_in` module.
5. Every pot is settled by `_award_pot` (via `complete_uncontested_hand` or `resolve_showdown`), which handles ties and the odd chip, eliminates busted players, and either ends the tournament or rotates the button.

Key invariants, re-checked by `assert_chip_invariants` after essentially every mutation: stacks plus pot always equal `TOTAL_CHIPS` (1500 chips are conserved, never created or destroyed), the pot equals the sum of in-hand contributions, and no card is ever duplicated across deck, board, and hole cards. Determinism comes entirely from seeds: the tournament seed plus `hand_seed` fixes each deck, so replaying the same seed and the same actions reproduces the same hands exactly — no randomness leaks in from the agent layer.
