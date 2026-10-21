"""Compact pandas tables for the PokerMind observation notebook.

Every function returns a DataFrame or Series so a notebook cell can simply call
it and let the returned value render as the cell output — no ``display()`` and
no Markdown wrapping.
"""

import json
from pathlib import Path
from typing import Any

import pandas as pd

# Show full cell text (e.g. an agent's whole REASON) instead of pandas' default clip.
pd.set_option("display.max_colwidth", None)

_PLAYERS = ("Conservative", "Aggressive", "Adaptive")
_SCORES = (
    ("decision_quality", "Decision"),
    ("strategy_consistency", "Strategy"),
    ("adaptation", "Adaptation"),
    ("reason_quality", "Reason"),
    ("tool_usage", "Tool"),
    ("overall_score", "Overall"),
)


def _n(value: object) -> str:
    """Thousands-separated integer, or an em dash when unavailable."""
    return f"{int(value):,}" if isinstance(value, (int, float)) else "—"


def _pct(value: object) -> str:
    return f"{float(value) * 100:.0f}%" if isinstance(value, (int, float)) else "—"


# --- decision-by-decision replay -----------------------------------------


def _print_hand(hand: dict[str, Any], names: dict[int, str]) -> None:
    b = hand["blinds"]
    board = " ".join(hand.get("board") or []) or "—"
    print(f"── Hand {hand['hand_number']}  ·  blinds {b['small']}/{b['big']}  ·  board {board}")
    holes = hand.get("hole_cards") or {}
    for seat in sorted(holes, key=int):
        print(f"      {names.get(int(seat), seat):<13} {' '.join(holes[seat])}")
    for d in hand.get("decisions", []):
        ex = d.get("final_executed")
        if not ex:
            continue
        amount = f" {ex['AMOUNT']}" if ex["ACTION"] in ("CALL", "RAISE") else ""
        print(f"   {d['street']:<8} {d['agent']:<13} {ex['ACTION']}{amount}")
        print(f"            ↳ {ex['REASON']}")
    winners = ", ".join(names.get(s, str(s)) for s in hand.get("winners", []))
    print(f"   → won by {winners or '—'}\n")


def show_hands(result: dict[str, Any], first: int = 2, last: int = 2) -> None:
    """Print the first and last few hands, decision by decision, readably."""
    hands = result["hands"]
    names = {p["seat"]: p["name"] for p in result["players"]}
    keep = sorted(set(range(min(first, len(hands))))
                  | set(range(max(0, len(hands) - last), len(hands))))
    for i in keep:
        _print_hand(hands[i], names)


# --- one hand -------------------------------------------------------------


def hand_actions(hand: dict[str, Any]) -> pd.DataFrame:
    """One row per decision in a single hand: who acted, how, and why."""
    rows = []
    for d in hand.get("decisions", []):
        executed = d.get("final_executed") or {}
        rows.append(
            {
                "Player": d["agent"],
                "Street": d["street"],
                "Action": executed.get("ACTION", "—"),
                "Amount": executed.get("AMOUNT", 0),
                "Reason": executed.get("REASON") or "",
            }
        )
    return pd.DataFrame(rows)


def hand_tokens(hand: dict[str, Any]) -> pd.Series:
    """Token spend for a single hand."""
    used = [
        d["usage"] for d in hand.get("decisions", []) if d["usage"]["usage_available"]
    ]
    return pd.Series(
        {
            "Decisions": len(hand.get("decisions", [])),
            "Input tokens": _n(sum(u["input_tokens"] for u in used)),
            "Output tokens": _n(sum(u["output_tokens"] for u in used)),
            "Total tokens": _n(sum(u["total_tokens"] for u in used)),
        },
        name="one hand",
    )


# --- one tournament -------------------------------------------------------


def tournament_result(result: dict[str, Any]) -> pd.Series:
    """Headline result of one tournament: the winner and how long it ran."""
    return pd.Series(
        {"Winner": result["winner"], "Hands played": result["metrics"]["hand_count"]},
        name="result",
    )


def player_metrics(result: dict[str, Any]) -> pd.DataFrame:
    """Per-agent behaviour and result for one tournament."""
    players = result["metrics"]["players"]
    rows = {}
    for name in _PLAYERS:
        p = players[name]
        rows[name] = {
            "Place": p["placement"],
            "Hands won": p["hands_won"],
            "Fold": _pct(p["action_rates"]["fold"]),
            "Call": _pct(p["action_rates"]["call"]),
            "Raise": _pct(p["action_rates"]["raise"]),
            "All-ins": p["all_ins"],
            "End stack": p["ending_stack"],
        }
    return pd.DataFrame(rows).T.sort_values("Place")


def player_tokens(result: dict[str, Any]) -> pd.Series:
    """Total player-model token spend for one tournament."""
    players = result["metrics"]["players"].values()
    return pd.Series(
        {
            "Model calls": sum(p["api_calls"] for p in players),
            "Input tokens": _n(sum(p["observed_usage"]["input_tokens"] for p in players)),
            "Output tokens": _n(sum(p["observed_usage"]["output_tokens"] for p in players)),
            "Total tokens": _n(sum(p["observed_usage"]["total_tokens"] for p in players)),
        },
        name="one tournament",
    )


# --- judge (one tournament) ----------------------------------------------


def judge_scores(result: dict[str, Any]) -> pd.DataFrame:
    """The 1-10 Judge scores per agent for one tournament, with judge calls made."""
    by_player = {e["player"]: e for e in result["judge_evaluations"]}
    rows = {}
    for name in _PLAYERS:
        record = by_player.get(name) or {}
        ev = record.get("evaluation") or {}
        row = {}
        for key, label in _SCORES:
            value = ev.get(key)
            score = value["score"] if isinstance(value, dict) else value
            row[label] = score if score is not None else "—"
        row["Calls"] = len(record.get("attempts", []))
        rows[name] = row
    return pd.DataFrame(rows).T


def judge_reasoning(result: dict[str, Any]) -> pd.DataFrame:
    """The Judge's written rationale per agent: one row per scored aspect."""
    by_player = {e["player"]: e for e in result["judge_evaluations"]}
    rows = []
    for name in _PLAYERS:
        ev = (by_player.get(name) or {}).get("evaluation") or {}
        for key, label in _SCORES:
            if key == "overall_score":
                continue
            value = ev.get(key)
            if isinstance(value, dict):
                score = value.get("score")
                rows.append({
                    "Agent": name,
                    "Aspect": label,
                    "Score": score if score is not None else "—",
                    "Reasoning": value.get("rationale", ""),
                })
        if ev.get("main_improvement"):
            rows.append({
                "Agent": name,
                "Aspect": "Main improvement",
                "Score": ev.get("overall_score", "—"),
                "Reasoning": ev["main_improvement"],
            })
    return pd.DataFrame(rows).set_index(["Agent", "Aspect"])


def judge_tokens(result: dict[str, Any]) -> pd.Series:
    """Judge token spend for one tournament."""
    u = result["metrics"]["judge_usage"]
    return pd.Series(
        {
            "Judge calls": u["api_calls"],
            "Input tokens": _n(u["input_tokens"]),
            "Output tokens": _n(u["output_tokens"]),
            "Total tokens": _n(u["total_tokens"]),
        },
        name="judge · one tournament",
    )


# --- three tournaments ----------------------------------------------------


def experiment_tournaments(summary: dict[str, Any]) -> pd.DataFrame:
    """One row per tournament in the three-tournament experiment."""
    rows = {}
    for i, t in enumerate(summary["tournaments"], 1):
        rows[f"Tournament {i}"] = {
            "Winner": t["winner"],
            "Hands": t["hands_played"],
            "Player tokens": _n(t["player_tokens"]),
            "Judge calls": t["judge_model_calls"],
            "Judge tokens": _n(t["judge_tokens"]),
            "Tool calls": t["tool_calls"],
        }
    return pd.DataFrame(rows).T


def load_tournaments(summary: dict[str, Any], results_dir: Any) -> list[dict[str, Any]]:
    """Load the three source tournament result dicts behind an experiment summary."""
    return [
        json.loads((Path(results_dir) / f).read_text())
        for f in summary["source_files"]
    ]


def tournament_stats(result: dict[str, Any], number: int) -> "pd.io.formats.style.Styler":
    """Per-agent stats for one tournament, captioned with its number and winner."""
    caption = (
        f"Tournament {number} · winner {result['winner']} "
        f"· {result['metrics']['hand_count']} hands"
    )
    return player_metrics(result).style.set_caption(caption)


def tournament_judges(result: dict[str, Any], number: int) -> "pd.io.formats.style.Styler":
    """Judge scores (with judge calls) for one tournament, captioned."""
    return judge_scores(result).style.set_caption(f"Tournament {number} · judge scores")


def experiment_agents(summary: dict[str, Any]) -> pd.DataFrame:
    """Aggregate per-agent results across the three tournaments."""
    rows = {}
    for name in _PLAYERS:
        a = summary["agents"][name]
        rows[name] = {
            "Tournament wins": a["tournament_wins"],
            "Avg place": round(sum(a["placements"]) / len(a["placements"]), 2),
            "Hands won": a["hands_won"],
            "Raise": _pct(a["action_rates"]["raise"]),
            "Player tokens": _n(a["player_usage"]["total_tokens"]),
        }
    return pd.DataFrame(rows).T


def experiment_tokens(summary: dict[str, Any]) -> pd.Series:
    """Total player-model spend across the three tournaments."""
    t = summary["totals"]
    return pd.Series(
        {
            "Model calls": t["player_model_calls"],
            "Tool calls": t["tool_calls"],
            "Input tokens": _n(t["player_input_tokens"]),
            "Output tokens": _n(t["player_output_tokens"]),
            "Total tokens": _n(t["player_total_tokens"]),
        },
        name="three tournaments",
    )


# --- judges (three tournaments) ------------------------------------------


def judge_averages(summary: dict[str, Any]) -> pd.DataFrame:
    """Average Judge scores per agent across the three tournaments."""
    rows = {}
    for name in _PLAYERS:
        avg = summary["agents"][name]["average_judge_scores"]
        rows[name] = {
            label: (round(avg[key], 1) if avg.get(key) is not None else "—")
            for key, label in _SCORES
        }
    return pd.DataFrame(rows).T


def experiment_judge_reasoning(summary: dict[str, Any], results_dir: Any) -> pd.DataFrame:
    """The Judge's headline written note per agent for each of the three tournaments."""
    rows = []
    for i, fname in enumerate(summary["source_files"], 1):
        t = json.loads((Path(results_dir) / fname).read_text())
        by_player = {e["player"]: e for e in t["judge_evaluations"]}
        for name in _PLAYERS:
            ev = (by_player.get(name) or {}).get("evaluation") or {}
            rows.append({
                "Tournament": i,
                "Agent": name,
                "Overall": ev.get("overall_score", "—"),
                "Main improvement": ev.get("main_improvement", ""),
            })
    return pd.DataFrame(rows).set_index(["Tournament", "Agent"])


def judge_experiment_tokens(summary: dict[str, Any]) -> pd.Series:
    """Total Judge spend across the nine evaluations."""
    t = summary["totals"]
    return pd.Series(
        {
            "Evaluations": summary["successful_judge_evaluations"],
            "Judge calls": t["judge_model_calls"],
            "Input tokens": _n(t["judge_input_tokens"]),
            "Output tokens": _n(t["judge_output_tokens"]),
            "Total tokens": _n(t["judge_total_tokens"]),
        },
        name="judges · three tournaments",
    )
