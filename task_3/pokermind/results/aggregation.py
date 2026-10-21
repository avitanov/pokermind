"""Three-tournament aggregate metrics derived from source JSON files."""

import copy
import json
from pathlib import Path

from task_3.pokermind.core.domain import (
    STARTING_STACK,
    PlayerName,
    TournamentStatus,
    empty_public_statistics,
)

EXPERIMENT_SCHEMA_VERSION = 1


def _new_agent_aggregate() -> dict[str, object]:
    return {
        "tournament_wins": 0,
        "placements": [],
        "hands_won": 0,
        "decisions": 0,
        "folds": 0,
        "checks": 0,
        "calls": 0,
        "raises": 0,
        "all_ins": 0,
        "tool_calls": {
            "get_opponent_statistics": 0,
            "peek_opponent_card": 0,
        },
        "tool_successes": {
            "get_opponent_statistics": 0,
            "peek_opponent_card": 0,
        },
        "invalid_outputs": 0,
        "retries": 0,
        "fallbacks": 0,
        "player_model_calls": 0,
        "player_usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        },
        "judge_scores": {
            "decision_quality": [],
            "strategy_consistency": [],
            "adaptation": [],
            "reason_quality": [],
            "overall_score": [],
            "tool_usage": [],
        },
    }


def _successful_judges(result: dict[str, object]) -> dict[str, dict[str, object]]:
    evaluations = result.get("judge_evaluations")
    if not isinstance(evaluations, list):
        raise ValueError("Tournament Judge evaluations must be a list.")
    completed = {
        str(record["player"]): record
        for record in evaluations
        if isinstance(record, dict) and record.get("status") == "completed"
    }
    if set(completed) != {player.value for player in PlayerName}:
        raise ValueError("Every source tournament requires three successful Judges.")
    return completed


def _add_agent_metrics(
    aggregate: dict[str, object], metrics: dict[str, object]
) -> None:
    for key in (
        "hands_won",
        "decisions",
        "folds",
        "checks",
        "calls",
        "raises",
        "all_ins",
        "invalid_outputs",
        "retries",
        "fallbacks",
    ):
        aggregate[key] = int(aggregate[key]) + int(metrics[key])
    aggregate["player_model_calls"] = int(aggregate["player_model_calls"]) + int(
        metrics["api_calls"]
    )
    for bucket in ("tool_calls", "tool_successes"):
        target = aggregate[bucket]
        source = metrics[bucket]
        if not isinstance(target, dict) or not isinstance(source, dict):
            raise TypeError("Tool metrics must be dictionaries.")
        for tool_name in target:
            target[tool_name] = int(target[tool_name]) + int(source[tool_name])
    usage = metrics["observed_usage"]
    aggregate_usage = aggregate["player_usage"]
    if not isinstance(usage, dict) or not isinstance(aggregate_usage, dict):
        raise TypeError("Observed player usage must be a dictionary.")
    for token_key in ("input_tokens", "output_tokens", "total_tokens"):
        aggregate_usage[token_key] = int(aggregate_usage[token_key]) + int(
            usage[token_key]
        )


def _add_judge_scores(aggregate: dict[str, object], record: dict[str, object]) -> None:
    evaluation = record.get("evaluation")
    score_lists = aggregate["judge_scores"]
    if not isinstance(evaluation, dict) or not isinstance(score_lists, dict):
        raise TypeError("Completed Judge records require structured scores.")
    for field in (
        "decision_quality",
        "strategy_consistency",
        "adaptation",
        "reason_quality",
    ):
        scored = evaluation.get(field)
        if not isinstance(scored, dict):
            raise TypeError(f"Judge field {field} must be a dictionary.")
        score_lists[field].append(int(scored["score"]))
    score_lists["overall_score"].append(int(evaluation["overall_score"]))
    tool_usage = evaluation.get("tool_usage")
    if isinstance(tool_usage, dict) and tool_usage.get("score") is not None:
        score_lists["tool_usage"].append(int(tool_usage["score"]))


def _finalize_agent_aggregate(aggregate: dict[str, object]) -> None:
    decisions = int(aggregate["decisions"])
    denominator = decisions or 1
    aggregate["action_rates"] = {
        action: int(aggregate[f"{action}s"]) / denominator
        for action in ("fold", "check", "call", "raise")
    }
    score_lists = aggregate.pop("judge_scores")
    if not isinstance(score_lists, dict):
        raise TypeError("Judge score lists must be a dictionary.")
    aggregate["average_judge_scores"] = {
        field: (sum(scores) / len(scores) if scores else None)
        for field, scores in score_lists.items()
    }


def create_experiment_summary(
    tournament_paths: list[Path], base_seed: int
) -> dict[str, object]:
    """Aggregate the fixed final experiment directly from three source JSON files."""
    if len(tournament_paths) != 3:
        raise ValueError("The final experiment requires exactly three tournaments.")
    agents = {player.value: _new_agent_aggregate() for player in PlayerName}
    tournaments: list[dict[str, object]] = []
    token_totals = {
        "player_input_tokens": 0,
        "player_output_tokens": 0,
        "player_total_tokens": 0,
        "judge_input_tokens": 0,
        "judge_output_tokens": 0,
        "judge_total_tokens": 0,
        "total_observed_tokens": 0,
    }
    total_player_calls = 0
    total_judge_calls = 0
    total_tool_calls = 0
    aggressive_raise_rate_wins = 0

    for index, path in enumerate(tournament_paths):
        result = json.loads(path.read_text(encoding="utf-8"))
        if result.get("status") != TournamentStatus.COMPLETED.value:
            raise ValueError(f"Source tournament {path.name} is not completed.")
        expected_seed = base_seed + index
        if result.get("seed") != expected_seed or result.get("initial_button") != index:
            raise ValueError("Final tournament seeds or initial buttons are incorrect.")
        initial = result.get("initial_state")
        if not isinstance(initial, dict):
            raise ValueError("Source tournament is missing its explicit initial state.")
        if sorted(initial.get("stacks", {}).values()) != [STARTING_STACK] * 3:
            raise ValueError(
                f"Every source tournament must start with {STARTING_STACK} chips "
                "per player."
            )
        expected_stats = {
            player.value: empty_public_statistics() for player in PlayerName
        }
        if initial.get("public_stats") != expected_stats:
            raise ValueError("Tournament-local statistics did not start empty.")
        if (
            initial.get("peek_available") is not True
            or initial.get("peek_observation") is not None
        ):
            raise ValueError("Adaptive peek state did not start fresh.")

        metrics = result.get("metrics")
        if not isinstance(metrics, dict) or not isinstance(
            metrics.get("players"), dict
        ):
            raise TypeError("Source tournament metrics are invalid.")
        judges = _successful_judges(result)
        player_metrics = metrics["players"]
        tournament_player_tokens = 0
        tournament_player_calls = 0
        tournament_tool_calls = 0
        tournament_retries = 0
        tournament_fallbacks = 0
        for player in PlayerName:
            current = player_metrics[player.value]
            if not isinstance(current, dict):
                raise TypeError("Player metrics must be dictionaries.")
            aggregate = agents[player.value]
            _add_agent_metrics(aggregate, current)
            placements = aggregate["placements"]
            if not isinstance(placements, list):
                raise TypeError("Aggregate placements must be a list.")
            placements.append(int(current["placement"]))
            aggregate["tournament_wins"] = int(aggregate["tournament_wins"]) + int(
                current["placement"] == 1
            )
            _add_judge_scores(aggregate, judges[player.value])
            usage = current["observed_usage"]
            if not isinstance(usage, dict):
                raise TypeError("Player observed usage must be a dictionary.")
            tournament_player_tokens += int(usage["total_tokens"])
            tournament_player_calls += int(current["api_calls"])
            tool_calls = current["tool_calls"]
            if not isinstance(tool_calls, dict):
                raise TypeError("Player tool calls must be a dictionary.")
            tournament_tool_calls += sum(int(value) for value in tool_calls.values())
            tournament_retries += int(current["retries"])
            tournament_fallbacks += int(current["fallbacks"])

        judge_usage = metrics.get("judge_usage")
        if not isinstance(judge_usage, dict):
            raise TypeError("Judge usage metrics must be a dictionary.")
        tournament_judge_tokens = int(judge_usage["total_tokens"])
        total_player_calls += tournament_player_calls
        total_judge_calls += int(judge_usage["api_calls"])
        total_tool_calls += tournament_tool_calls
        for token_key in ("input_tokens", "output_tokens", "total_tokens"):
            player_value = sum(
                int(player_metrics[player.value]["observed_usage"][token_key])
                for player in PlayerName
            )
            judge_value = int(judge_usage[token_key])
            token_totals[f"player_{token_key}"] += player_value
            token_totals[f"judge_{token_key}"] += judge_value

        conservative_raise = float(
            player_metrics[PlayerName.CONSERVATIVE.value]["action_rates"]["raise"]
        )
        aggressive_raise = float(
            player_metrics[PlayerName.AGGRESSIVE.value]["action_rates"]["raise"]
        )
        aggressive_won = aggressive_raise > conservative_raise
        aggressive_raise_rate_wins += int(aggressive_won)
        adaptive = player_metrics[PlayerName.ADAPTIVE.value]
        tournaments.append(
            {
                "tournament_id": result["tournament_id"],
                "source_file": path.name,
                "seed": result["seed"],
                "initial_button": result["initial_button"],
                "winner": result["winner"],
                "placements": copy.deepcopy(result["placements"]),
                "hands_played": metrics["hand_count"],
                "raise_rates": {
                    player.value: player_metrics[player.value]["action_rates"]["raise"]
                    for player in PlayerName
                },
                "adaptive_statistics_calls": adaptive["tool_calls"][
                    "get_opponent_statistics"
                ],
                "adaptive_peek_successes": adaptive["tool_successes"][
                    "peek_opponent_card"
                ],
                "retries": tournament_retries,
                "fallbacks": tournament_fallbacks,
                "player_model_calls": tournament_player_calls,
                "judge_model_calls": judge_usage["api_calls"],
                "tool_calls": tournament_tool_calls,
                "player_tokens": tournament_player_tokens,
                "judge_tokens": tournament_judge_tokens,
                "total_observed_tokens": (
                    tournament_player_tokens + tournament_judge_tokens
                ),
                "aggressive_raise_rate_higher": aggressive_won,
            }
        )

    for aggregate in agents.values():
        _finalize_agent_aggregate(aggregate)
    token_totals["total_observed_tokens"] = (
        token_totals["player_total_tokens"] + token_totals["judge_total_tokens"]
    )
    return {
        "schema_version": EXPERIMENT_SCHEMA_VERSION,
        "base_seed": base_seed,
        "tournament_count": 3,
        "source_files": [path.name for path in tournament_paths],
        "tournaments": tournaments,
        "agents": agents,
        "totals": {
            "player_model_calls": total_player_calls,
            "judge_model_calls": total_judge_calls,
            "tool_calls": total_tool_calls,
            **token_totals,
            "planning_target_tokens": 400_000,
        },
        "strategy_criterion": {
            "description": (
                "Aggressive raise rate > Conservative raise rate in at least 2 of "
                "3 tournaments"
            ),
            "tournaments_satisfied": aggressive_raise_rate_wins,
            "passed": aggressive_raise_rate_wins >= 2,
        },
        "successful_judge_evaluations": 9,
    }
