"""Direct, bounded single-attempt dispatch to one player agent.

The acting player is always known before the call, so a decision is just a
direct Strands ``Agent`` invocation with per-call limits — no routing graph.
"""

import copy

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)
from strands import Agent
from strands.types.exceptions import EventLoopException, ModelThrottledException

from task_3.pokermind.agents.configuration import PLAYER_INVOCATION_LIMITS
from task_3.pokermind.agents.schemas import (
    InvocationResponse,
    PlayerProviderStreamError,
)
from task_3.pokermind.core.domain import PlayerName, TournamentState

_WRAPPED_TRANSIENT_ERRORS = (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
    ModelThrottledException,
)


def invoke_player_once(
    agents: dict[PlayerName, Agent],
    state: TournamentState,
    actor: int,
    prompt: str,
    attempt: int,
) -> InvocationResponse:
    """Run one bounded attempt for the acting player and collect its tool activity.

    The agent's conversation history is reset afterward so each attempt is
    stateless. Transient provider failures are re-raised as
    ``PlayerProviderStreamError`` for the coordinator's retry handling.
    """
    player = state.players[actor].name
    agent = agents[player]
    original_messages = copy.deepcopy(getattr(agent, "messages", []))
    invocation_state = {
        "actor": player.value,
        "tournament_state": state if player is PlayerName.ADAPTIVE else None,
        "tool_events": [],
        "tool_call_count": 0,
        "attempt": attempt,
    }
    try:
        try:
            result = agent(
                prompt,
                invocation_state=invocation_state,
                limits=PLAYER_INVOCATION_LIMITS,
            )
        except APIError as error:
            raise PlayerProviderStreamError(
                "The model provider rejected or interrupted its response stream."
            ) from error
        except EventLoopException as error:
            if isinstance(error.original_exception, _WRAPPED_TRANSIENT_ERRORS):
                raise PlayerProviderStreamError(
                    "The model provider failed during the Strands event loop."
                ) from error
            raise
        return InvocationResponse(
            result=result,
            tool_events=copy.deepcopy(invocation_state["tool_events"]),
            tool_call_count=invocation_state["tool_call_count"],
        )
    finally:
        agent.messages = original_messages
