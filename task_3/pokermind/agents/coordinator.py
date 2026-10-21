"""Bounded model retries, failure categorization, and action execution."""

import copy
import json

from langfuse import Langfuse
from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)
from strands.agent import AgentResult
from strands.types.exceptions import MaxTokensReachedException, ModelThrottledException

from task_3.pokermind.agents.configuration import (
    MAX_DECISION_ATTEMPTS,
    _LIMIT_STOP_REASONS,
)
from task_3.pokermind.agents.schemas import (
    DecisionAttemptRecord,
    DecisionOutcome,
    InvokeOnce,
    PlayerProviderStreamError,
    PokerDecisionValidationError,
    StructuredDecisionError,
)
from task_3.pokermind.agents.state import build_visible_state
from task_3.pokermind.agents.validation import (
    _api_fallback_decision,
    _fallback_decision,
    _invocation_parts,
    _mark_api_failure,
    _proposal_record,
    _revert_uncommitted_peek,
    _structured_correction_message,
    build_correction_message,
    execute_validated_decision,
    normalize_usage,
    parse_and_validate_decision,
)
from task_3.pokermind.core.domain import TournamentState
from task_3.pokermind.observability import (
    player_attempt_scope,
    player_decision_scope,
    update_current_observation,
)

_TRANSIENT_API_ERRORS = (
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
    InternalServerError,
    ModelThrottledException,
    PlayerProviderStreamError,
)


def coordinate_decision(
    state: TournamentState,
    actor: int,
    invoke_once: InvokeOnce,
    telemetry_client: Langfuse | None = None,
) -> DecisionOutcome:
    """Run one model call plus five retries, then recover deterministically."""
    visible_state = build_visible_state(state, actor)
    legal_action_copy = copy.deepcopy(visible_state["legal_actions"])
    if not isinstance(legal_action_copy, list):
        raise AssertionError("Visible legal actions must be a list.")
    base_prompt = json.dumps(visible_state, sort_keys=True, separators=(",", ":"))
    prompt = base_prompt
    attempts: list[DecisionAttemptRecord] = []
    final_category: str | None = None

    with player_decision_scope(
        telemetry_client, state, actor, visible_state
    ) as decision_client:
        for attempt_number in range(1, MAX_DECISION_ATTEMPTS + 1):
            result: AgentResult | None = None
            tool_events: list[dict[str, object]] = []
            tool_call_count = 0
            # Remember the one-time peek state so an attempt that spends it but
            # then fails can hand it back (retries / later decisions may peek).
            peek_available_before = state.peek_available
            peek_observation_before = copy.deepcopy(state.adaptive_peek_observation)

            def revert_peek() -> None:
                _revert_uncommitted_peek(
                    state, peek_available_before, peek_observation_before, tool_events
                )

            with player_attempt_scope(
                decision_client, state, actor, attempt_number
            ) as attempt_client:
                try:
                    response = invoke_once(prompt, attempt_number)
                    result, tool_events, tool_call_count = _invocation_parts(response)
                    decision = parse_and_validate_decision(state, actor, result)
                except _TRANSIENT_API_ERRORS as error:
                    revert_peek()
                    final_category = "api_failure"
                    update_current_observation(
                        attempt_client,
                        level="ERROR",
                        status_message="Transient model invocation failed.",
                        category=final_category,
                    )
                    state.counters["api_failures"] += 1
                    attempts.append(
                        DecisionAttemptRecord(
                            attempt=attempt_number,
                            category=final_category,
                            error=(
                                f"{type(error).__name__}: transient model invocation failed"
                            ),
                            proposal=None,
                            tool_events=[],
                            tool_call_count=0,
                            usage=normalize_usage(result),
                            retry=attempt_number < MAX_DECISION_ATTEMPTS,
                            prompt=prompt,
                        )
                    )
                    hand = state.current_hand
                    if hand is None:
                        raise ValueError("No hand is active.")
                    state.events.append(
                        {
                            "event": "decision_api_failure",
                            "hand_number": hand.hand_number,
                            "street": hand.street.value,
                            "actor": actor,
                            "attempt": attempt_number,
                        }
                    )
                    prompt = base_prompt
                    continue
                except MaxTokensReachedException:
                    revert_peek()
                    final_category = "structured_output"
                    update_current_observation(
                        attempt_client,
                        level="WARNING",
                        status_message="Agent invocation limit reached.",
                        category="agent_limit",
                    )
                    attempts.append(
                        DecisionAttemptRecord(
                            attempt=attempt_number,
                            category=final_category,
                            error="Agent invocation reached the model token limit.",
                            proposal=None,
                            tool_events=copy.deepcopy(tool_events),
                            tool_call_count=tool_call_count,
                            usage=normalize_usage(result),
                            retry=attempt_number < MAX_DECISION_ATTEMPTS,
                            prompt=prompt,
                        )
                    )
                    prompt = (
                        f"{base_prompt}\nStructured output failed: model token limit "
                        "reached. Return only ACTION, AMOUNT, and REASON."
                    )
                    continue
                except (
                    StructuredDecisionError,
                    PokerDecisionValidationError,
                ) as error:
                    revert_peek()
                    final_category = error.category
                    limit_failure = (
                        result is not None and result.stop_reason in _LIMIT_STOP_REASONS
                    )
                    update_current_observation(
                        attempt_client,
                        level="WARNING",
                        status_message=(
                            "Agent invocation limit reached."
                            if limit_failure
                            else "Agent decision was rejected."
                        ),
                        category="agent_limit" if limit_failure else final_category,
                    )
                    attempts.append(
                        DecisionAttemptRecord(
                            attempt=attempt_number,
                            category=final_category,
                            error=str(error),
                            proposal=(
                                _proposal_record(result) if result is not None else None
                            ),
                            tool_events=copy.deepcopy(tool_events),
                            tool_call_count=tool_call_count,
                            usage=normalize_usage(result),
                            retry=attempt_number < MAX_DECISION_ATTEMPTS,
                            prompt=prompt,
                        )
                    )
                    correction = (
                        build_correction_message(error)
                        if isinstance(error, PokerDecisionValidationError)
                        else _structured_correction_message(state, actor, error)
                    )
                    prompt = f"{base_prompt}\n{correction}"
                    continue

                usage = normalize_usage(result)
                attempts.append(
                    DecisionAttemptRecord(
                        attempt=attempt_number,
                        category="success",
                        error=None,
                        proposal=decision.model_dump(by_alias=True),
                        tool_events=copy.deepcopy(tool_events),
                        tool_call_count=tool_call_count,
                        usage=usage,
                        retry=False,
                        prompt=prompt,
                    )
                )
                update_current_observation(
                    attempt_client,
                    level="DEFAULT",
                    status_message="Agent decision accepted.",
                    category="success",
                    output={
                        **decision.model_dump(by_alias=True),
                        "usage": usage,
                    },
                )
                execute_validated_decision(state, actor, decision)
                update_current_observation(
                    decision_client,
                    level="DEFAULT",
                    status_message="Agent action executed.",
                    category="success",
                    output=decision.model_dump(by_alias=True),
                )
                return DecisionOutcome(
                    decision,
                    attempts,
                    False,
                    False,
                    visible_state,
                    legal_action_copy,
                )

        if final_category == "api_failure":
            if state.counters.get("api_fallbacks", 0) == 0:
                fallback = _api_fallback_decision(state, actor)
                execute_validated_decision(state, actor, fallback)
                state.counters["api_fallbacks"] = 1
                hand = state.current_hand
                if hand is None:
                    raise ValueError("No hand is active.")
                state.events.append(
                    {
                        "event": "decision_api_fallback",
                        "hand_number": hand.hand_number,
                        "street": hand.street.value,
                        "actor": actor,
                        "action": fallback.action.value,
                    }
                )
                update_current_observation(
                    decision_client,
                    level="WARNING",
                    status_message="API retry budget exhausted; fallback executed.",
                    category="api_fallback",
                    output=fallback.model_dump(by_alias=True),
                )
                return DecisionOutcome(
                    fallback,
                    attempts,
                    True,
                    False,
                    visible_state,
                    legal_action_copy,
                )
            _mark_api_failure(state, actor, attempts)
            update_current_observation(
                decision_client,
                level="ERROR",
                status_message="Decision API retry budget exhausted.",
                category="api_failure",
            )
            return DecisionOutcome(
                None,
                attempts,
                False,
                True,
                visible_state,
                legal_action_copy,
            )

        fallback = _fallback_decision(state, actor)
        execute_validated_decision(state, actor, fallback)
        update_current_observation(
            decision_client,
            level="WARNING",
            status_message="Deterministic fallback executed.",
            category="fallback",
            output=fallback.model_dump(by_alias=True),
        )
        return DecisionOutcome(
            fallback,
            attempts,
            True,
            False,
            visible_state,
            legal_action_copy,
        )
