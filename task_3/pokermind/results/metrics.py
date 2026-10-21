"""Deterministic metrics derived only from executed tournament behavior."""


def compute_metrics(result: dict[str, object]) -> dict[str, object]:
    """Derive tournament metrics exclusively from final executed decisions."""
    players = result["players"]
    hands = result["hands"]
    if not isinstance(players, list) or not isinstance(hands, list):
        raise TypeError("Tournament players and hands must be lists.")
    placements = result.get("placements", {})
    player_metrics: dict[str, dict[str, object]] = {
        str(player["name"]): {
            "placement": placements.get(player["name"]),
            "ending_stack": int(player["starting_stack"]),
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
            "api_calls": 0,
            "observed_usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            },
        }
        for player in players
        if isinstance(player, dict)
    }

    for hand in hands:
        if not isinstance(hand, dict):
            continue
        decisions = hand.get("decisions", [])
        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            metrics = player_metrics[str(decision["agent"])]
            attempts = decision.get("attempts", [])
            if isinstance(attempts, list):
                metrics["api_calls"] = int(metrics["api_calls"]) + len(attempts)
                metrics["retries"] = int(metrics["retries"]) + max(0, len(attempts) - 1)
                metrics["invalid_outputs"] = int(metrics["invalid_outputs"]) + sum(
                    isinstance(attempt, dict)
                    and attempt.get("category")
                    in {"structured_output", "poker_validation"}
                    for attempt in attempts
                )
            for event in decision.get("tool_events", []):
                if not isinstance(event, dict):
                    continue
                tool_name = event.get("tool")
                tool_calls = metrics["tool_calls"]
                tool_successes = metrics["tool_successes"]
                if tool_name in tool_calls:
                    tool_calls[tool_name] += 1
                    tool_result = event.get("result")
                    if isinstance(tool_result, dict) and tool_result.get("ok") is True:
                        tool_successes[tool_name] += 1
            usage = decision.get("usage")
            if isinstance(usage, dict) and usage.get("usage_available") is True:
                observed = metrics["observed_usage"]
                for key in ("input_tokens", "output_tokens", "total_tokens"):
                    observed[key] += int(usage[key])

            executed = decision.get("final_executed")
            if not isinstance(executed, dict):
                continue
            metrics["decisions"] = int(metrics["decisions"]) + 1
            action_key = f"{str(executed['ACTION']).lower()}s"
            metrics[action_key] = int(metrics[action_key]) + 1
            metrics["all_ins"] = int(metrics["all_ins"]) + int(
                decision.get("all_in") is True
            )
            metrics["fallbacks"] = int(metrics["fallbacks"]) + int(
                decision.get("fallback_used") is True
            )

        winners = hand.get("winners", [])
        for seat in winners:
            name = str(players[int(seat)]["name"])
            player_metrics[name]["hands_won"] = (
                int(player_metrics[name]["hands_won"]) + 1
            )
        ending_stacks = hand.get("ending_stacks")
        if isinstance(ending_stacks, dict):
            for player in players:
                name = str(player["name"])
                player_metrics[name]["ending_stack"] = int(
                    ending_stacks[str(player["seat"])]
                )

    for metrics in player_metrics.values():
        decisions = int(metrics["decisions"])
        denominator = decisions or 1
        metrics["action_rates"] = {
            "fold": int(metrics["folds"]) / denominator,
            "check": int(metrics["checks"]) / denominator,
            "call": int(metrics["calls"]) / denominator,
            "raise": int(metrics["raises"]) / denominator,
        }
    judge_usage = {
        "successful_evaluations": 0,
        "failed_evaluations": 0,
        "api_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }
    evaluations = result.get("judge_evaluations", [])
    if isinstance(evaluations, list):
        for evaluation in evaluations:
            if not isinstance(evaluation, dict):
                continue
            completed = evaluation.get("status") == "completed"
            key = "successful_evaluations" if completed else "failed_evaluations"
            judge_usage[key] += 1
            attempts = evaluation.get("attempts", [])
            if isinstance(attempts, list):
                judge_usage["api_calls"] += len(attempts)
            usage = evaluation.get("usage")
            if isinstance(usage, dict) and usage.get("usage_available") is True:
                for token_key in ("input_tokens", "output_tokens", "total_tokens"):
                    judge_usage[token_key] += int(usage[token_key])

    return {
        "hand_count": len(hands),
        "winner": result.get("winner"),
        "players": player_metrics,
        "judge_usage": judge_usage,
    }
