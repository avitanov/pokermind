"""Bounded independent Judge model invocation and result validation.

The Judge is a single stateless "system prompt + trace -> structured JSON" call,
so it talks to OpenRouter through the OpenAI SDK directly rather than a Strands
agent. The compact trace, the ``JudgeEvaluation`` schema, and the bounded
retry/validation loop remain the substance of the evaluation.
"""

import copy
import os

from langfuse import Langfuse
from openai import (
    APIError,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
    OpenAI,
)
from openai.types.chat import ParsedChatCompletion
from pydantic import ValidationError

from task_3.pokermind.agents import OPENROUTER_BASE_URL, OPENROUTER_TIMEOUT_SECONDS
from task_3.pokermind.core.domain import JUDGE_MODEL_ID, PlayerName
from task_3.pokermind.evaluation.schemas import (
    JUDGE_INVOCATION_LIMITS,
    MAX_JUDGE_ATTEMPTS,
    JudgeAttemptRecord,
    JudgeEvaluation,
    JudgeOutputError,
)
from task_3.pokermind.evaluation.traces import (
    compact_player_trace,
    render_judge_prompt,
)
from task_3.pokermind.observability import (
    judge_attempt_scope,
    update_current_observation,
)

_JUDGE_PROMPT = """You are an independent poker decision-quality Judge.
Evaluate only the supplied player's observable decisions and concise reasons.
For every decision, use only the state shown as visible at that decision time.
Do not infer hidden cards, future cards, or private reasoning. Do not reward or
penalize a decision merely because its eventual hand outcome was lucky or unlucky.
Score strategy consistency against the supplied strategy summary. Tool usage is
applicable only when the input says it is applicable. Return the structured
JudgeEvaluation fields and no additional commentary."""


def create_judge_client() -> OpenAI:
    """Create the OpenRouter client for the fixed independent Judge model."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required to create the Judge.")
    return OpenAI(
        api_key=api_key,
        base_url=OPENROUTER_BASE_URL,
        timeout=OPENROUTER_TIMEOUT_SECONDS,
        max_retries=0,
    )


def invoke_judge_once(
    client: OpenAI, prompt: str, attempt: int
) -> ParsedChatCompletion[JudgeEvaluation]:
    """Run one bounded Judge completion with the schema-constrained response.

    Transient API errors propagate to the caller, which categorizes and retries
    them. Truncation/content-filter completions are returned (not raised) so the
    caller can record usage and treat them as retryable structured-output misses.
    """
    del attempt
    try:
        return client.chat.completions.parse(
            model=JUDGE_MODEL_ID,
            messages=[
                {"role": "system", "content": _JUDGE_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format=JudgeEvaluation,
            temperature=0.1,
            max_tokens=JUDGE_INVOCATION_LIMITS["output_tokens"],
            extra_body={"reasoning": {"exclude": True}},
        )
    except (LengthFinishReasonError, ContentFilterFinishReasonError) as error:
        return error.completion


def _unavailable_usage() -> dict[str, int | bool | None]:
    return {
        "usage_available": False,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }


def _judge_usage(
    completion: ParsedChatCompletion[JudgeEvaluation],
) -> dict[str, int | bool | None]:
    """Read observed token usage from a completion without estimating."""
    usage = getattr(completion, "usage", None)
    values = {
        "input_tokens": getattr(usage, "prompt_tokens", None),
        "output_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values.values()):
        return _unavailable_usage()
    return {"usage_available": True, **values}


def _validate_evaluation(
    completion: ParsedChatCompletion[JudgeEvaluation],
    compact_trace: dict[str, object],
    player: PlayerName,
) -> JudgeEvaluation:
    """Validate one completion into a schema-and-invariant-checked evaluation."""
    choice = completion.choices[0]
    if choice.finish_reason == "length":
        raise JudgeOutputError("Judge response was truncated at the output token limit.")
    if choice.finish_reason == "content_filter":
        raise JudgeOutputError("Judge response was blocked by a content filter.")

    evaluation = getattr(choice.message, "parsed", None)
    if not isinstance(evaluation, JudgeEvaluation):
        content = choice.message.content
        if not content:
            raise JudgeOutputError("Judge result is missing structured output.")
        try:
            evaluation = JudgeEvaluation.model_validate_json(content)
        except ValidationError as error:
            raise JudgeOutputError(f"Invalid structured Judge output: {error}") from error

    expected_applicable = player is PlayerName.ADAPTIVE
    if evaluation.tool_usage.applicable is not expected_applicable:
        raise JudgeOutputError("Judge tool applicability does not match the player.")
    references = {
        (int(decision["hand"]), str(decision["street"]))
        for decision in compact_trace["decisions"]
        if isinstance(decision, dict)
    }
    for reference in (evaluation.strongest_decision, evaluation.weakest_decision):
        if (reference.hand_number, reference.street.value) not in references:
            raise JudgeOutputError(
                "Judge decision reference is not in the compact trace."
            )
    return evaluation


def _combined_usage(attempts: list[JudgeAttemptRecord]) -> dict[str, object]:
    observed = [
        attempt.usage for attempt in attempts if attempt.usage["usage_available"]
    ]
    if not observed:
        return _unavailable_usage()
    return {
        "usage_available": True,
        "input_tokens": sum(int(usage["input_tokens"]) for usage in observed),
        "output_tokens": sum(int(usage["output_tokens"]) for usage in observed),
        "total_tokens": sum(int(usage["total_tokens"]) for usage in observed),
    }


def _serialize_attempts(attempts: list[JudgeAttemptRecord]) -> list[dict[str, object]]:
    return [
        {
            "attempt": attempt.attempt,
            "category": attempt.category,
            "error": attempt.error,
            "usage": copy.deepcopy(attempt.usage),
            "retry": attempt.retry,
        }
        for attempt in attempts
    ]


def evaluate_player(
    tournament_json: dict[str, object],
    player: PlayerName,
    invoke_once,
    telemetry_client: Langfuse | None = None,
) -> dict[str, object]:
    """Run at most two Judge attempts and return a non-mutating result record."""
    compact_trace = compact_player_trace(tournament_json, player)
    prompt = render_judge_prompt(compact_trace)
    attempts: list[JudgeAttemptRecord] = []

    for attempt_number in range(1, MAX_JUDGE_ATTEMPTS + 1):
        with judge_attempt_scope(
            telemetry_client,
            tournament_id=str(tournament_json["tournament_id"]),
            evaluated_player=player,
            attempt=attempt_number,
            model=JUDGE_MODEL_ID,
            judge_input=compact_trace,
        ) as attempt_client:
            try:
                completion = invoke_once(prompt, attempt_number)
            except APIError as error:
                # Transient throttling/timeouts and any other provider-side failure
                # (e.g. a rejected request) both fail this evaluation gracefully
                # instead of crashing the tournament.
                attempts.append(
                    JudgeAttemptRecord(
                        attempt_number,
                        "api_failure",
                        f"{type(error).__name__}: Judge invocation failed",
                        _unavailable_usage(),
                        attempt_number < MAX_JUDGE_ATTEMPTS,
                    )
                )
                update_current_observation(
                    attempt_client,
                    level="ERROR",
                    status_message="Judge invocation failed.",
                    category="api_failure",
                )
                continue

            usage = _judge_usage(completion)
            try:
                evaluation = _validate_evaluation(completion, compact_trace, player)
            except JudgeOutputError as error:
                attempts.append(
                    JudgeAttemptRecord(
                        attempt_number,
                        "structured_output",
                        str(error),
                        usage,
                        attempt_number < MAX_JUDGE_ATTEMPTS,
                    )
                )
                update_current_observation(
                    attempt_client,
                    level="WARNING",
                    status_message="Structured Judge output was rejected.",
                    category="structured_output",
                )
                continue

            attempts.append(
                JudgeAttemptRecord(attempt_number, "success", None, usage, False)
            )
            evaluation_data = evaluation.model_dump(mode="json")
            update_current_observation(
                attempt_client,
                level="DEFAULT",
                status_message="Judge evaluation accepted.",
                category="success",
                output={"evaluation": evaluation_data, "usage": usage},
            )
            return {
                "player": player.value,
                "model": JUDGE_MODEL_ID,
                "status": "completed",
                "attempts": _serialize_attempts(attempts),
                "usage": _combined_usage(attempts),
                "evaluation": evaluation_data,
                "error": None,
            }

    final_category = attempts[-1].category
    return {
        "player": player.value,
        "model": JUDGE_MODEL_ID,
        "status": "failed",
        "attempts": _serialize_attempts(attempts),
        "usage": _combined_usage(attempts),
        "evaluation": None,
        "error": {
            "category": final_category,
            "message": "Judge evaluation failed after two bounded attempts.",
        },
    }
