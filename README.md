# PokerMind

**Internship project:** This work was completed as part of the Loka Machine Learning Internship. References to "Week X", task numbers, and labs follow the original internship curriculum.

Developed by Atanas Vitanov during the Loka ML internship.

A multi-agent Texas Hold'em experiment:

- deterministic cards, betting, tournament lifecycle, chip, and all-in logic;
- Conservative, Aggressive, and Adaptive Strands agents with Adaptive tools;
- structured decision validation, retries, fallbacks, checkpoints, replay, and JSON results;
- Gemini Judge evaluations and Langfuse observability for decisions, tools, retries, and model usage;
- notebooks for live tournaments, observability, reporting, and the replay presentation;
- deterministic unit tests for the poker engine.

## Setup

Run commands from this directory, using the project environment:

```bash
uv sync
cp .env.example .env
```

Set `OPENROUTER_API_KEY` in `.env` for live model calls. Set
`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL` to enable
Langfuse tracing. Never commit `.env` or credentials.

## Run

Run the tests:

```bash
uv run python -m unittest discover -s task_3/tests -v
```

Open the notebooks:

```bash
uv run jupyter lab task_3/notebooks/pokermind_live.ipynb
uv run jupyter lab task_3/notebooks/pokermind_observability.ipynb
```

The notebooks run a single tournament or the three-tournament experiment and
display metrics, Judge scores, token usage, and replay data. Generated output
is written under `task_3/results/`; runtime logs are written under
`task_3/logs/`.
