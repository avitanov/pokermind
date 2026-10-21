# `utils/` — notebook setup and compact result tables

Presentation-only helpers for the observation notebook. Two files, no core logic.

## Files

### `__init__.py` — `prepare_notebook(root) -> (results_dir, notebook_results_dir, log_path)`
Loads `.env`, points a `task_3` file logger at `logs/pokermind_notebook.log` (idempotent — safe to re-run a cell), quiets the `strands`/`openai` loggers, and returns the two result directories the notebook writes to. No network, no LLM.

### `report.py` — pandas tables for each notebook section
Every function takes a result/summary dict and returns a `pandas.DataFrame` or `Series`, so a notebook cell just calls it and lets the value render as the cell output (no `display()`, no Markdown). Pure formatting — no I/O.

| Function | Returns |
|---|---|
| `hand_actions(hand)` | one row per decision: Player, Street, Action, Amount, Reason |
| `hand_tokens(hand)` | token spend for a single hand |
| `player_metrics(result)` | per-agent Place / Hands won / Fold·Call·Raise % / All-ins / End stack |
| `player_tokens(result)` | total player-model spend for one tournament |
| `judge_scores(result)` | 1–10 Judge scores per agent (Decision, Strategy, Adaptation, Reason, Tool, Overall) |
| `judge_tokens(result)` | Judge spend for one tournament |
| `experiment_tournaments(summary)` | per-tournament winner / hands / tokens / tool calls |
| `experiment_agents(summary)` | aggregate per-agent wins / avg place / hands won / raise % / tokens |
| `experiment_tokens(summary)` | total player-model spend across three tournaments |
| `judge_averages(summary)` | average Judge scores per agent across the nine evaluations |
| `judge_experiment_tokens(summary)` | total Judge spend across the nine evaluations |

Private helpers: `_n` (thousands-separated int, `—` when missing) and `_pct` (fraction → `NN%`).

## How it fits together
The notebook's setup cell calls `prepare_notebook`; each of the five sections calls one `report.*` table function plus its matching `*_tokens` function. Nothing else imports `utils` — it is notebook-only.
