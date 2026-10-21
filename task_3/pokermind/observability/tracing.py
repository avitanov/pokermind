"""Best-effort Langfuse scopes over Strands' native OpenTelemetry spans."""

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

from langfuse import Langfuse, get_client, propagate_attributes

from task_3.pokermind.core.domain import PLAYER_MODEL_ID, PlayerName, TournamentState


LOGGER = logging.getLogger(__name__)
_REQUIRED_ENVIRONMENT = (
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
)


def _warn(operation: str, error: Exception) -> None:
    LOGGER.warning("Langfuse %s unavailable: %s", operation, type(error).__name__)


def initialize_observability() -> Langfuse | None:
    """Initialize the official Langfuse OpenTelemetry client when configured."""
    if any(not os.environ.get(name) for name in _REQUIRED_ENVIRONMENT):
        return None
    try:
        return get_client()
    except Exception as error:
        _warn("initialization", error)
        return None


@contextmanager
def _observation_scope(
    client: Langfuse | None,
    *,
    name: str,
    input_value: object,
    session_id: str,
    tags: list[str],
    metadata: dict[str, str],
    trace_name: str | None,
) -> Iterator[Langfuse | None]:
    if client is None:
        yield None
        return

    observation_manager = None
    propagation_manager = None
    try:
        observation_manager = client.start_as_current_observation(
            as_type="span",
            name=name,
            input=input_value,
            metadata=metadata,
        )
        observation_manager.__enter__()
        propagation_manager = propagate_attributes(
            session_id=session_id,
            tags=tags,
            trace_name=trace_name,
            metadata=metadata,
        )
        propagation_manager.__enter__()
    except Exception as error:
        _warn("trace scope", error)
        if observation_manager is not None:
            try:
                observation_manager.__exit__(None, None, None)
            except Exception as close_error:
                _warn("trace cleanup", close_error)
        yield None
        return

    try:
        yield client
    finally:
        if propagation_manager is not None:
            try:
                propagation_manager.__exit__(None, None, None)
            except Exception as error:
                _warn("attribute cleanup", error)
        if observation_manager is not None:
            try:
                observation_manager.__exit__(None, None, None)
            except Exception as error:
                _warn("trace cleanup", error)


def _player_metadata(
    state: TournamentState, actor: int
) -> tuple[PlayerName, dict[str, str]]:
    hand = state.current_hand
    if hand is None:
        raise ValueError("A hand must be active before tracing a player decision.")
    player = state.players[actor].name
    return player, {
        "tournamentid": state.tournament_id,
        "handnumber": str(hand.hand_number),
        "street": hand.street.value,
        "agentname": player.value,
        "strategy": player.value,
        "model": PLAYER_MODEL_ID,
    }


@contextmanager
def player_decision_scope(
    client: Langfuse | None,
    state: TournamentState,
    actor: int,
    visible_state: dict[str, object],
) -> Iterator[Langfuse | None]:
    """Create one decision trace that owns the bounded attempt observations."""
    player, metadata = _player_metadata(state, actor)
    with _observation_scope(
        client,
        name="poker-player-decision",
        input_value=visible_state,
        session_id=state.tournament_id,
        tags=["pokermind", "player", player.value.lower()],
        metadata=metadata,
        trace_name="poker-player-decision",
    ) as active_client:
        yield active_client


@contextmanager
def player_attempt_scope(
    client: Langfuse | None,
    state: TournamentState,
    actor: int,
    attempt: int,
) -> Iterator[Langfuse | None]:
    """Create one child span for a model/Graph attempt and its native spans."""
    player, metadata = _player_metadata(state, actor)
    metadata.update(
        {
            "attempt": str(attempt),
            "retry": str(attempt > 1).lower(),
        }
    )
    with _observation_scope(
        client,
        name="poker-player-attempt",
        input_value={"attempt": attempt, "retry": attempt > 1},
        session_id=state.tournament_id,
        tags=["pokermind", "player", player.value.lower()],
        metadata=metadata,
        trace_name=None,
    ) as active_client:
        yield active_client


@contextmanager
def judge_attempt_scope(
    client: Langfuse | None,
    *,
    tournament_id: str,
    evaluated_player: PlayerName,
    attempt: int,
    model: str,
    judge_input: dict[str, object],
) -> Iterator[Langfuse | None]:
    """Create the bounded Judge attempt scope used by the later Judge step."""
    metadata = {
        "tournamentid": tournament_id,
        "evaluatedplayer": evaluated_player.value,
        "attempt": str(attempt),
        "retry": str(attempt > 1).lower(),
        "model": model,
    }
    with _observation_scope(
        client,
        name="poker-judge-evaluation",
        input_value=judge_input,
        session_id=tournament_id,
        tags=["pokermind", "judge", evaluated_player.value.lower()],
        metadata=metadata,
        trace_name="poker-judge-evaluation",
    ) as active_client:
        yield active_client


def update_current_observation(
    client: Langfuse | None,
    *,
    level: Literal["DEFAULT", "WARNING", "ERROR"],
    status_message: str,
    category: str,
    output: object | None = None,
) -> None:
    """Update the active application span without affecting poker execution."""
    if client is None:
        return
    try:
        client.update_current_span(
            level=level,
            status_message=status_message,
            metadata={"category": category},
            output=output,
        )
    except Exception as error:
        _warn("span update", error)


def flush_observability(client: Langfuse | None) -> None:
    """Best-effort flush after a tournament or short diagnostic."""
    if client is None:
        return
    try:
        client.flush()
    except Exception as error:
        _warn("flush", error)


