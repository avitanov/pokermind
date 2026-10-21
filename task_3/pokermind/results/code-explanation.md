# `results/` — build and persist the tournament JSON audit record

This subpackage owns the tournament "result document": a plain nested `dict` that is JSON-serializable and grows as a tournament plays out. It creates the document from engine state, records every hand and bounded decision, derives per-agent metrics purely from executed behavior, writes atomic snapshots to disk, embeds a runtime checkpoint for exact resume, replays saved actions through the engine to verify determinism, and finally aggregates three completed tournaments into one experiment summary. All public entry points are re-exported from `__init__.py`.

## Files

### `document.py` — create the result document and hand replay snapshots
- `create_tournament_result(state, *, started_at=None) -> dict` — Returns a **new** result dict with schema/id/seed/models/fixed-rules metadata, the players list, a captured `initial_state`, and empty `hands`/`metrics`/`placements`/`judge_evaluations`/`resume_history`/`errors` collections. Embeds the initial `runtime_checkpoint`. Raises `ValueError` if the tournament has already started (`hand_number != 0` or an active `current_hand`). No file I/O.
- `record_hand_start(result, state) -> None` — **Mutates** `result`: appends a new hand record (hand number, seed, hole cards, blinds, positions, starting stacks, empty replay fields) to `result["hands"]` and re-syncs the runtime checkpoint. Raises `ValueError` if no seeded hand is active or the hand number is already recorded; `TypeError` if `hands` is not a list.
- `SCHEMA_VERSION` — result document schema version constant (currently `2`).
- `_seat_map`, `_player_stacks`, `_hand_record`, `_sync_hand_replay` — private helpers reused across the package. `_player_stacks(state)` returns `{seat_str: stack}`; `_hand_record(result, n)` locates an existing hand record (raises `ValueError` if missing); `_sync_hand_replay(record, hand)` **mutates** a hand record in place with board, public actions, all-in caps/refunds/contributions, showdown results, winners, pot awards, and eliminations.

### `checkpoint.py` — JSON-safe runtime checkpoints for exact continuation
- `runtime_checkpoint(state) -> dict` — Returns a **new** JSON-safe snapshot of all deterministic runtime state (tournament fields, per-seat players, serialized current hand incl. deck, public stats, peek state, events, counters). Cards are stored as short-name strings. No mutation, no I/O.
- `sync_runtime_checkpoint(result, state) -> None` — **Mutates** `result` by replacing `result["runtime_checkpoint"]` with a fresh checkpoint.
- `restore_runtime_checkpoint(result) -> TournamentState` — Rebuilds and validates a `TournamentState` from `result["runtime_checkpoint"]`. Raises `ValueError` if the checkpoint is missing, has an unsupported version, or its tournament id/seed mismatch the result; runs `assert_chip_invariants` and verifies 52 unique cards when a hand is active. Returns a new state; does not mutate `result`.
- `prepare_resumed_result(result, state) -> None` — **Mutates both** `result` and `state` to reset only terminal markers for a resume: appends a `resume_history` entry (preserving the prior failure), sets status back to `IN_PROGRESS`, clears completion/winner/placements/judge evaluations, and re-syncs the checkpoint. Raises `ValueError` if the tournament is already `COMPLETED`.
- `CHECKPOINT_VERSION` — checkpoint schema version constant (currently `1`).
- `_cards`, `_json_value`, `_int_map`, `_serialize_hand`, `_restore_hand` — private serialization/deserialization helpers (deep-copy scalars, sort int-keyed maps to string keys, (de)serialize a `HandState`).

### `decisions.py` — decision, completion, placement, and Judge records
- `record_decision(result, state, actor, outcome) -> None` — **Mutates** `result`: builds one bounded decision record (attempts, tool events, final executed action, failure categories, all-in flag, stacks/pot after) and appends it to the current hand's `decisions`, then calls `record_hand_progress`. Logs at INFO. Raises `TypeError`/`ValueError` on malformed visible state.
- `record_hand_progress(result, state) -> None` — **Mutates** `result`: re-syncs the current hand's replay fields and the runtime checkpoint. Raises `ValueError` if no current hand.
- `record_hand_completion(result, state) -> None` — **Mutates** `result`: requires the current hand to be completed; syncs replay, writes the hand's `ending_stacks`, recomputes `result["metrics"]`, and re-syncs the checkpoint. Raises `ValueError` if the hand is missing/incomplete.
- `finalize_tournament_result(result, state, *, completed_at=None) -> None` — **Mutates** `result`: sets final status/winner, computes `placements` (winner first, others ordered by elimination hand), appends any `state.failure` to `errors`, recomputes metrics, and syncs the checkpoint. Raises `ValueError` if the tournament is still `IN_PROGRESS`.
- `add_judge_evaluation(result, evaluation) -> None` — **Mutates** `result`: inserts or replaces a deep-copied Judge evaluation keyed by evaluated `player`, then recomputes metrics. Raises `ValueError` if the player is missing, multiple records already exist, or a completed evaluation already exists for that player.
- `_attempt_record`, `_decision_usage`, `_placements` — private helpers (serialize one decision attempt; sum available token usage across attempts; compute finishing order).

### `metrics.py` — deterministic metrics from executed behavior
- `compute_metrics(result) -> dict` — Returns a **new** metrics dict derived only from recorded hands/decisions and Judge evaluations: per-player `placement`, `ending_stack`, `hands_won`, decision/action counts, `action_rates`, tool call/success tallies, invalid outputs, retries, fallbacks, api calls, and observed token usage; plus `hand_count`, `winner`, and aggregate `judge_usage` (successful/failed evaluations, api calls, tokens). Does not mutate `result` (callers assign the return into `result["metrics"]`). Raises `TypeError` if `players`/`hands` are not lists.

### `persistence.py` — atomic JSON snapshot and summary persistence
- `write_snapshot(result, output_directory) -> Path` — **File I/O.** Atomically writes the result to `tournament_<id>.json` (completed) or `tournament_<id>.in_progress.json` (otherwise); on completion also unlinks any stale in-progress file. Returns the written path. Raises `ResultWriteError` on write failure; validates the tournament id.
- `load_snapshot(path) -> dict` — **File I/O (read only).** Loads a snapshot without modifying or deleting it. Raises `SnapshotLoadError` on read/JSON errors or if the root is not a JSON object.
- `write_experiment_summary(summary, output_directory) -> Path` — **File I/O.** Atomically writes the aggregation to `experiment_summary.json`; returns the path. Raises `ResultWriteError` on failure.
- `ResultWriteError(OSError)` — raised when an atomic snapshot cannot be written.
- `SnapshotLoadError(ValueError)` — raised when a snapshot cannot be loaded.
- `_safe_tournament_id`, `_write_json_atomic` — private helpers; `_write_json_atomic` writes to a temp file in the target directory, fsyncs, and `replace()`s into place (crash-safe), cleaning up the temp file on error.

### `replay.py` — deterministic replay reconstruction
- `replay_tournament(result) -> TournamentState` — Rebuilds a fresh tournament from `id`/`seed`/`initial_button` and re-executes every recorded action through the engine (`create_tournament`, `start_hand`, `advance_street`, `apply_action`), asserting that seeds, blinds, positions, stacks, hole cards, board, public actions, showdown, winners, pot awards, eliminations, ending stacks, final status, and winner all match the saved record exactly. Returns the reconstructed state. No I/O and no mutation of `result`; raises `AssertionError`/`ValueError`/`TypeError` on any mismatch (public-action comparison ignores the free-text `reason` field).

### `aggregation.py` — three-tournament experiment summary
- `create_experiment_summary(tournament_paths, base_seed) -> dict` — **File I/O (read only).** Loads exactly three completed source tournament JSON files, validates each (completed status, expected `seed = base_seed + index`, `initial_button == index`, clean starting stacks/stats/peek state, and three successful Judges), then aggregates per-agent stats (placements, wins, action counts/rates, tool calls, usage, averaged Judge scores), per-tournament rows, token/model-call totals, and a strategy criterion (aggressive raise rate > conservative in >= 2 of 3). Returns a **new** summary dict. Raises `ValueError`/`TypeError` on any validation failure.
- `EXPERIMENT_SCHEMA_VERSION` — experiment summary schema version constant (currently `1`).
- `_new_agent_aggregate`, `_successful_judges`, `_add_agent_metrics`, `_add_judge_scores`, `_finalize_agent_aggregate` — private accumulation helpers (mutate the per-agent aggregate dicts in place).

### `__init__.py` — public API
Re-exports the 14 public functions the runner uses via `__all__`. Submodule-only names (`compute_metrics`, `runtime_checkpoint`, `sync_runtime_checkpoint`, and the `persistence` error classes) are imported directly from their modules where needed, not from the package.

## How it fits together

The result dict has a single lifecycle. `create_tournament_result(state)` produces the empty document (with an initial `runtime_checkpoint`). As the engine runs, `record_hand_start` appends each dealt hand; `record_decision` appends each executed decision and, via `record_hand_progress`, keeps the hand's public replay fields and the runtime checkpoint in sync; `record_hand_completion` seals a hand's ending stacks and recomputes `metrics`. When the tournament ends, `finalize_tournament_result` sets the winner/placements/errors and metrics. Afterwards `add_judge_evaluation` attaches one LLM-Judge record per player (recomputing `judge_usage` metrics) without touching any poker outcome. At any point `write_snapshot` persists the whole dict atomically — in-progress under a `.in_progress.json` name, final under the plain name.

Resume works through the embedded `runtime_checkpoint`: every mutating recorder re-syncs it, so a snapshot always carries enough JSON-safe state to reconstruct the exact `TournamentState`. To continue an interrupted run, `load_snapshot` reads the file, `restore_runtime_checkpoint` rebuilds and validates the state (chip invariants + 52 unique cards), and `prepare_resumed_result` flips terminal markers back to in-progress while logging the prior failure into `resume_history`. `replay_tournament` is the determinism check: it re-drives the recorded actions through the engine and asserts every observable field matches, proving the record is faithful and reproducible.

Finally, `create_experiment_summary` reads three completed tournament files (seeds `base_seed`, `base_seed+1`, `base_seed+2`; buttons 0/1/2), aggregates per-agent metrics and averaged Judge scores, tallies token/model-call/tool totals, and reports the strategy criterion (aggressive raises more often than conservative in at least 2 of 3 tournaments); `write_experiment_summary` persists it to `experiment_summary.json`.
