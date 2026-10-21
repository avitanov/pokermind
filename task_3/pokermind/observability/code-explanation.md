# `observability/` — best-effort Langfuse/OpenTelemetry tracing scopes over Strands' native spans

This subpackage layers optional Langfuse tracing on top of the OpenTelemetry spans that Strands emits natively. Everything is *best-effort*: `initialize_observability()` returns `None` when the required environment variables are missing, and every other function accepts that `None` client and cleanly no-ops (yielding `None` for scopes, returning early for updates/flush/shutdown). Any Langfuse exception is caught and logged as a warning rather than propagated, so tracing failures never interrupt poker execution. Callers pass the returned client (or `None`) into the scope helpers.

## Files

### `tracing.py` — the tracing implementation (init, scopes, updates, flush/shutdown)

- `initialize_observability() -> Langfuse | None` — Returns `None` immediately if any of `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` is unset. Otherwise calls Langfuse `get_client()` (network-backed client); on any exception, logs a warning and returns `None`. This `None` is what propagates the graceful-degradation behavior to every other function.
- `player_decision_scope(client, state, actor, visible_state) -> Iterator[Langfuse | None]` — Context manager. Opens the top-level decision trace (`poker-player-decision`) for one player's turn, tagged with the player name and keyed on the tournament id as session id; input is the player's `visible_state`. Yields the active client (or `None` when unconfigured/failed). Sends span data to Langfuse when configured.
- `player_attempt_scope(client, state, actor, attempt) -> Iterator[Langfuse | None]` — Context manager. Opens a child span (`poker-player-attempt`) nested under the decision trace for a single model/Graph attempt (adds `attempt` and `retry` metadata). Yields the active client or `None`. Network-backed when configured.
- `judge_attempt_scope(client, *, tournament_id, evaluated_player, attempt, model, judge_input) -> Iterator[Langfuse | None]` — Context manager. Opens a bounded scope (`poker-judge-evaluation`) for one LLM-judge attempt, tagged `judge` plus the evaluated player, with `attempt`/`retry`/`model` metadata. Yields the active client or `None`. Network-backed when configured.
- `update_current_observation(client, *, level, status_message, category, output=None) -> None` — Updates the currently active span with a level (`"DEFAULT" | "WARNING" | "ERROR"`), status message, `category` metadata, and optional output. No-ops when `client is None`; catches and warns on failure. Network-backed when configured.
- `flush_observability(client) -> None` — Best-effort `client.flush()` (network call) to push buffered spans; no-op on `None`, warns on failure.
- `shutdown_observability(client) -> None` — Best-effort flush then `client.shutdown()` for a short-lived process; no-op on `None`, each step guarded independently and warns on failure. Network calls when configured.
- `_observation_scope(client, *, name, input_value, session_id, tags, metadata, trace_name) -> Iterator[Langfuse | None]` — Private context manager underlying all scopes. When `client is None` it yields `None` and returns. Otherwise it enters a Langfuse `start_as_current_observation(as_type="span", ...)` and a `propagate_attributes(...)` context, yields the client, and tears both down in `finally`. Setup/teardown failures are caught, warned, and downgraded to yielding `None`.
- `_player_metadata(state, actor) -> tuple[PlayerName, dict[str, str]]` — Private helper building the metadata dict (tournament id, hand number, street, agent/strategy name, model) for a player; raises `ValueError` if no hand is active.
- `_warn(operation, error) -> None` — Private helper logging a warning with the operation name and exception type.
- `Langfuse` — The official Langfuse client type (imported), returned by `initialize_observability` and threaded through every helper.

### `__init__.py` — public API surface

- Re-exports and defines `__all__` for the public functions: `flush_observability`, `initialize_observability`, `judge_attempt_scope`, `player_attempt_scope`, `player_decision_scope`, `shutdown_observability`, `update_current_observation`. The private helpers and scope internals are not exported.

## How it fits together

At process startup the experiment runner (or a short diagnostic) calls `initialize_observability()` once and holds the returned client — `None` if Langfuse is not configured. During play, the coordinator wraps each player's turn in `player_decision_scope(...)`, and each model/Graph retry inside it in `player_attempt_scope(...)`; the LLM-judge step wraps each evaluation attempt in `judge_attempt_scope(...)`. Within any scope, code may call `update_current_observation(...)` to annotate the active span with a level/status/output. When the tournament (or diagnostic) ends, the runner calls `flush_observability(client)` and finally `shutdown_observability(client)`. Because every function accepts and short-circuits on `None`, the same call sites work unchanged whether or not Langfuse is configured.
