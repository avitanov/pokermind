"""External preflight and completed-tournament integrity validation."""

import json
import os
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from task_3.pokermind.core.domain import (
    TOTAL_CHIPS,
    PlayerName,
    TournamentState,
    TournamentStatus,
)
from task_3.pokermind.evaluation import compact_player_trace
from task_3.pokermind.results import replay_tournament

OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"
OPENROUTER_PREFLIGHT_TIMEOUT_SECONDS = 10.0


class ExperimentPreflightError(RuntimeError):
    """The fixed external model configuration is unusable before dealing."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _preflight_openrouter() -> None:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ExperimentPreflightError(
            "OPENROUTER_API_KEY is required before dealing a tournament."
        )
    request = Request(
        OPENROUTER_KEY_URL,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urlopen(request, timeout=OPENROUTER_PREFLIGHT_TIMEOUT_SECONDS) as response:
            payload = json.load(response)
    except HTTPError as error:
        raise ExperimentPreflightError(
            f"OpenRouter credential preflight failed with HTTP {error.code}."
        ) from error
    except (URLError, OSError, ValueError, TypeError) as error:
        raise ExperimentPreflightError(
            f"OpenRouter credential preflight failed: {type(error).__name__}."
        ) from error
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ExperimentPreflightError(
            "OpenRouter key preflight returned invalid data."
        )
    if data.get("is_free_tier") is True:
        raise ExperimentPreflightError(
            "OpenRouter credits are required for PokerMind's fixed paid models."
        )
    remaining = data.get("limit_remaining")
    if isinstance(remaining, (int, float)) and not isinstance(remaining, bool):
        if remaining <= 0:
            raise ExperimentPreflightError(
                "The OpenRouter API key credit limit is exhausted."
            )


def _decision_matches_legal_action(decision: dict[str, object]) -> bool:
    executed = decision.get("final_executed")
    legal_actions = decision.get("legal_actions")
    if not isinstance(executed, dict) or not isinstance(legal_actions, list):
        return False
    action = executed.get("ACTION")
    amount = executed.get("AMOUNT")
    for legal in legal_actions:
        if not isinstance(legal, dict) or legal.get("action") != action:
            continue
        if legal.get("amount") is not None:
            return amount == legal["amount"]
        minimum = legal.get("min_amount")
        maximum = legal.get("max_amount")
        return (
            isinstance(amount, int)
            and isinstance(minimum, int)
            and isinstance(maximum, int)
            and minimum <= amount <= maximum
        )
    return False


def validate_completed_result(result: dict[str, object]) -> TournamentState:
    """Apply the deterministic portion of the one-tournament integration gate."""
    if result.get("status") != TournamentStatus.COMPLETED.value:
        raise AssertionError("The integration result is not completed.")
    replayed = replay_tournament(result)
    stacks = [player.stack for player in replayed.players.values()]
    if sorted(stacks) != [0, 0, TOTAL_CHIPS]:
        raise AssertionError(
            f"A completed integration tournament must end {TOTAL_CHIPS}/0/0."
        )

    hands = result.get("hands")
    if not isinstance(hands, list) or not hands:
        raise AssertionError("A completed integration tournament requires hands.")
    peek_successes = 0
    for expected_number, hand in enumerate(hands, 1):
        if not isinstance(hand, dict) or hand.get("hand_number") != expected_number:
            raise AssertionError("Recorded hand numbers must be consecutive.")
        ending_stacks = hand.get("ending_stacks")
        if (
            not isinstance(ending_stacks, dict)
            or sum(ending_stacks.values()) != TOTAL_CHIPS
        ):
            raise AssertionError(
                f"Every completed hand must preserve {TOTAL_CHIPS} chips."
            )
        for decision in hand.get("decisions", []):
            if not isinstance(decision, dict):
                raise AssertionError("Each recorded decision must be a dictionary.")
            required = {
                "visible_state",
                "legal_actions",
                "tool_events",
                "attempts",
                "ACTION",
                "AMOUNT",
                "REASON",
                "final_executed",
            }
            if not required.issubset(decision):
                raise AssertionError("A recorded decision is missing required fields.")
            if decision.get("api_failed") is True:
                if decision.get("final_executed") is not None:
                    raise AssertionError(
                        "An API-failed decision cannot execute an action."
                    )
                continue
            if not _decision_matches_legal_action(decision):
                raise AssertionError(
                    "A recorded final action was not legal when executed."
                )
            for event in decision["tool_events"]:
                if (
                    isinstance(event, dict)
                    and event.get("tool") == "peek_opponent_card"
                    and isinstance(event.get("result"), dict)
                    and event["result"].get("ok") is True
                ):
                    peek_successes += 1
    if peek_successes > 1:
        raise AssertionError("Adaptive peek succeeded more than once.")

    evaluations = result.get("judge_evaluations")
    if not isinstance(evaluations, list) or len(evaluations) != len(PlayerName):
        raise AssertionError("Exactly three Judge evaluations are required.")
    evaluated_players = {
        evaluation.get("player")
        for evaluation in evaluations
        if isinstance(evaluation, dict) and evaluation.get("status") == "completed"
    }
    if evaluated_players != {player.value for player in PlayerName}:
        raise AssertionError("Every player requires one successful Judge evaluation.")
    for player in PlayerName:
        compact_player_trace(result, player)
    return replayed
