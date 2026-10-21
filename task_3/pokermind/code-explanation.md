# `pokermind/` — package overview

PokerMind is a modified No-Limit Texas Hold'em tournament in which three LLM
agents — **Conservative**, **Aggressive**, and **Adaptive** — play until one
player holds all chips. The package cleanly separates **deterministic poker
logic** (no LLM) from **LLM decision-making**, so the game rules can be tested
and replayed without any model calls.

Each subfolder has its own `code-explanation.md` documenting every function and class.

## Architecture at a glance

```
core/         shared vocabulary: enums, cards, state dataclasses, the
              ACTION/AMOUNT/REASON decision schema, constants, model IDs
                     │  (imported by everything)
                     ▼
engine/       deterministic poker rules: deal, blinds, legal actions,
              betting, simplified all-in, showdown, elimination, chip
              invariants. Pure functions over TournamentState/HandState.
                     │  legal actions ▲ apply action │
                     ▼                                │
agents/       the three Strands LLM players: model config, per-actor
              visible-state builder (information isolation), the two
              Adaptive tools (opponent stats + one-time card peek),
              structured-output validation/retry, decision coordinator.
                     │  every executed decision │
                     ▼                          ▼
results/      builds & persists the tournament JSON audit record: hands,
              decisions, per-agent metrics, atomic snapshots, runtime
              checkpoints (resume), deterministic replay, and the
              three-tournament aggregation summary.
observability/ best-effort Langfuse/OpenTelemetry spans around each model
              call; no-ops cleanly when unconfigured.
                     │
                     ▼
evaluation/   LLM-as-Judge (different model family): builds a compact,
              visibility-safe per-player trace and scores each agent.
                     │
                     ▼
experiment/   top-level orchestration: run one hand, run/resume one
              tournament, run the fixed three-tournament final experiment;
              credential preflight and the completed-result integrity gate.
```

## Data flow for a single decision

1. `engine` computes the acting seat and its **legal actions**.
2. `agents.build_visible_state` builds a JSON view containing **only** what
   that actor may see (own hole cards, board, public actions, stacks).
3. The Strands agent returns a structured `ACTION / AMOUNT / REASON`.
4. `agents.validation` checks it against the engine's legal actions, retrying
   on invalid output and falling back to a safe legal action if needed.
5. `engine.apply_action` mutates the state; `results` records the decision and
   writes a snapshot; `observability` emits a span.

## Resume / crash-recovery

Play is snapshotted after **every decision**, so a crash mid-tournament resumes
from the exact hand and acting player without re-spending earlier calls. The
Judge phase is **idempotent**: only evaluations that are not yet completed are
(re)run, so a crash during judging — or an offline rerun of a fully-judged
tournament — never replays the poker hands. See `experiment/code-explanation.md`.

## Folder map

| Folder | Responsibility | Doc |
|---|---|---|
| `core/` | Domain model, enums, state dataclasses, constants | [core/code-explanation.md](core/code-explanation.md) |
| `engine/` | Deterministic poker rules (no LLM) | [engine/code-explanation.md](engine/code-explanation.md) |
| `agents/` | LLM players, tools, validation, Strands dispatch | [agents/code-explanation.md](agents/code-explanation.md) |
| `results/` | Tournament JSON record, metrics, snapshots, replay | [results/code-explanation.md](results/code-explanation.md) |
| `observability/` | Best-effort Langfuse/OTel tracing | [observability/code-explanation.md](observability/code-explanation.md) |
| `evaluation/` | LLM-as-Judge and compact traces | [evaluation/code-explanation.md](evaluation/code-explanation.md) |
| `experiment/` | Orchestration, resume, integrity gate | [experiment/code-explanation.md](experiment/code-explanation.md) |
| `utils/` | Notebook Markdown views (presentation only) | [utils/code-explanation.md](utils/code-explanation.md) |

## What is NOT here (by design)

No side pots, antes, database, network multiplayer, cross-tournament memory, or
a generic poker framework. The JSON record is only detailed enough to replay or
animate a tournament without rerunning the agents.
