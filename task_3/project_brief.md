# Project Brief: PokerMind — Multi-Agent Texas Hold’em Tournament

## 1. Task

PokerMind is a modified No-Limit Texas Hold’em environment in which three LLM agents — a **Conservative Agent, Aggressive Agent, and Adaptive Agent** — compete across multiple hands until only one player remains with chips.

The project targets several of the required complexity criteria: **multi-agent coordination, a real reasoning loop, multiple tools, state/memory, and graceful failure handling**. Every decision depends on the latest cards, betting state, chip stacks, opponent actions, and newly available observations rather than following a fixed sequence of predefined actions.

The final experiment consists of **three independent tournaments**. Every tournament starts with 500 chips per player, and tournament-specific memory is reset before the next tournament.

---

## 2. Architecture & Models

The system separates deterministic poker logic from LLM decision making. A Python poker engine controls cards, blinds, chip stacks, betting stages, legal actions, showdown evaluation, player elimination, and tournament completion. The LLM agents receive only the state they are allowed to observe and decide which legal action to take.

The multi-agent system uses the **Strands Graph pattern**. This pattern fits PokerMind because the execution path is state-driven and cyclic: one agent acts, the game state changes, another agent acts, the betting stage may change, and the process repeats across multiple hands. Strands Graph supports deterministic dependency-based orchestration and cyclic execution, which fits this controlled environment better than a Swarm, where agents autonomously hand work between each other.

All three poker agents use the same OpenRouter model:

`deepseek/deepseek-v4-flash`, pinned to the Cloudflare provider

Using the same model for Conservative, Aggressive, and Adaptive keeps model capability fixed so that differences are mainly caused by their strategy prompts and available tools. Provider routing is pinned to Cloudflare through OpenRouter and does not fall back to another host.

The post-tournament LLM Judge uses:

`google/gemini-3-flash-preview`

A different model family is deliberately used for evaluation so that the poker agents are not effectively evaluating themselves. Gemini 3 Flash Preview is currently available through OpenRouter and is positioned for reasoning, agentic workflows, and tool-use workloads.

The Adaptive Agent has two Strands tools. The first returns opponent statistics calculated only from public actions observed during the **current tournament**. The second allows it to reveal one randomly selected hole card from one selected opponent exactly once during the tournament.

Every poker decision must return:

`ACTION`, `AMOUNT`, and `REASON`.

The `REASON` is a short observable explanation based only on information available to that agent at the moment of the decision. Every action, reason, tool call, card state, and tournament result is stored in JSON for later evaluation and replay.

Langfuse is used for observability throughout the experiment, including tracing agent decisions, tool calls, model usage, retries, and tournament execution.

PokerMind intentionally simplifies standard No-Limit Texas Hold’em by not implementing side pots. When a player goes all-in, the remaining active players may call up to the capped amount or fold. Once the all-in is resolved, betting closes and the remaining community cards are revealed.

The blinds increase every two completed hands using the progression:

`25/50 → 75/100 → 150/200 → 200/300 → 400/700 → 700/1000 → 1000/1500`.

---

## 3. Success Definition

The main success criterion is that all **three tournaments complete from the initial deal until only one player remains**, without the system crashing or executing an illegal poker action.

Throughout each tournament, poker state must remain valid. Total tournament chips must remain 1,500, and private opponent cards must never be exposed to another agent except through the Adaptive Agent's valid one-time peek.

Every executed decision must be present in the tournament JSON with its `ACTION`, `AMOUNT`, and `REASON`. The resulting JSON must contain enough information to reconstruct the tournament later without rerunning the player agents.

The three strategy prompts should also create observable behavioral differences. As a predefined test, the Aggressive Agent should have a higher raise rate than the Conservative Agent in at least **two of the three tournaments**.

The Adaptive Agent must demonstrate actual tool-based behavior. Its statistics tool must operate only on information accumulated during the current tournament, and its opponent-card peek must never successfully execute more than once in a tournament.

Failure recovery will be tested deliberately by providing at least one invalid or malformed agent response. The response should be rejected, retried once, and recovered from without terminating the tournament.

Finally, after every tournament, each of the three agents must receive an LLM Judge evaluation covering decision quality, strategy consistency, adaptation, reason quality, tool usage where applicable, and an overall score.

---

## 4. Token Usage Estimate

The main source of token usage will be the poker-agent decisions. With the accelerated blind structure, the expected tournament length is roughly **8–12 hands**, although the exact number depends on agent behavior and cards. If a hand produces approximately **6–10 LLM decisions**, the three tournaments should require roughly **144–360 poker-agent decisions**.

Each player decision will use a compact state representation rather than the complete tournament transcript. A normal call is expected to contain approximately **400–700 input tokens** and around **30–70 output tokens**, since the response only needs `ACTION`, `AMOUNT`, and a short `REASON`. This gives an estimated player-agent usage of approximately **60,000–280,000 tokens** across the three tournaments.

Adaptive Agent tool calls create some additional model turns because the returned statistics or peek result must be processed before the final action. A reasonable allowance for these tool interactions is approximately **10,000–30,000 additional tokens** across the experiment.

There are also **nine Judge calls**: three agents evaluated after each of three tournaments. Instead of giving the Judge the complete raw JSON, each call will receive a compact structured trace containing only the evaluated player's decisions, visible state, reasons, and relevant outcomes. Assuming roughly **4,000–8,000 input tokens** and **300–500 output tokens** per Judge call, the Judge stage should require approximately **40,000–75,000 tokens**.

The expected final three-tournament experiment is therefore approximately:

> **110,000–385,000 total tokens**

A practical planning target is to remain below approximately **400,000 tokens** for the final experiment. Development and debugging calls are not included in this estimate.

To prevent token growth, agents will not receive the full previous tournament conversation on every turn. Each decision receives only the current poker state, relevant actions from the current hand, and necessary tournament information. Opponent history is retrieved through the statistics tool rather than repeatedly inserting the entire tournament transcript into every prompt.

---

## 5. Failure Modes

One likely failure is an agent returning malformed structured output, omitting its `REASON`, or selecting an action that is not currently legal. The poker engine will reject the response, return the validation problem and legal actions, and allow up to five retries. If the sixth attempt is still invalid, a deterministic safe fallback action will be executed so that the tournament can continue.

Invalid betting amounts are handled in the same way. The deterministic poker engine validates amounts rather than trusting the LLM and allows up to two bounded correction attempts when necessary.

The Adaptive Agent may attempt to use its card-peek tool more than once. The restriction is enforced by deterministic tournament state rather than only by the prompt. Any later attempt returns that the peek has already been consumed.

OpenRouter rate limits or temporary model failures could interrupt a tournament. Each decision therefore allows the initial call plus five retries. The first exhausted API sequence executes a legal deterministic fold, or a check when folding is not legal, and continues. If a later decision also exhausts all API attempts in the same tournament, the error is recorded and the tournament ends with `status = "failed"` without inventing another action or winner.

Atomic in-progress snapshots include a private deterministic runtime checkpoint. A failed or interrupted tournament can therefore continue from the same hand, acting player, cards, stacks, statistics, and Adaptive peek state instead of starting again. The failed proposal remains in the audit record and does not count as an executed poker action.

Another risk is excessive token consumption caused by too many hands, long responses, accumulated conversation history, or repeated tool calls. The accelerated blinds, compact state representation, short `REASON` outputs, bounded tool calls, bounded retries, and three-tournament limit are intended to keep the experiment within the planned token range.

---

## 6. Evaluation

The experiment consists of three tournaments using the same starting stacks, blind progression, poker-agent model, strategy prompts, tools, and poker rules. The initial dealer position rotates between tournaments so that each agent begins one tournament on the Button.

After every tournament, objective statistics such as tournament placement, hands won, fold rate, call rate, raise rate, all-in count, tool usage, invalid responses, retries, token usage, and API-call count are collected.

The independent Judge is then called three times per tournament, once for Conservative, once for Aggressive, and once for Adaptive. This produces **nine Judge evaluations** across the complete experiment.

The Judge evaluates actions primarily according to the information available to the player when each decision occurred, rather than simply rewarding decisions that happened to win. This is necessary because individual poker outcomes contain substantial randomness.

Because only three tournaments are performed, the final results will be treated as observations about agent behavior rather than statistically strong evidence that one strategy is objectively superior.

---

## 7. Timeline

### Day 1 — Poker Environment

The first day focuses on the deterministic environment. The poker engine will be implemented with card dealing, blinds, betting stages, legal actions, showdown evaluation, the simplified all-in rule, chip tracking, player elimination, heads-up play, and tournament completion.

### Day 2 — Agents, Tools, and Logging

The second day focuses on the agentic system. The Conservative, Aggressive, and Adaptive Strands agents will be integrated using DeepSeek V4 Flash on Cloudflare through OpenRouter, with mandatory `ACTION`, `AMOUNT`, and `REASON` outputs. The Adaptive Agent's current-tournament statistics tool and one-time card-peek tool will be added, together with structured-output validation, retries, deterministic fallbacks, and tournament JSON logging.

### Day 3 — Evaluation and Final Experiment

The final day focuses on evaluation and testing. The Gemini 3 Flash Preview Judge will be integrated, failure-recovery scenarios will be tested, and the three final tournaments will be executed. The resulting JSON files, deterministic metrics, Judge scores, strategy differences, tool usage, and total token consumption will then be compared and summarized for the final demonstration.
