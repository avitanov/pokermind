"""Strict structured output schema for independent Judge evaluations."""

from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from task_3.pokermind.core.domain import Street

MAX_JUDGE_ATTEMPTS = 2
# Plain bounds used to cap Judge output tokens and for notebook display.
JUDGE_INVOCATION_LIMITS = {
    "turns": 2,
    "output_tokens": 1_400,
    "total_tokens": 12_000,
}
_Rationale = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500, strict=True),
]


class ScoredRationale(BaseModel):
    """One bounded Judge score and its concise observable rationale."""

    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=1, le=10, strict=True)
    rationale: _Rationale


class ToolUsageEvaluation(BaseModel):
    """Tool-use score with explicit non-applicable behavior."""

    model_config = ConfigDict(extra="forbid")

    applicable: bool = Field(strict=True)
    score: int | None = Field(default=None, ge=1, le=10, strict=True)
    rationale: _Rationale

    @model_validator(mode="after")
    def validate_applicability(self) -> "ToolUsageEvaluation":
        """Require a score exactly when tool usage applies."""
        if self.applicable != (self.score is not None):
            raise ValueError("Tool score must be present exactly when applicable.")
        return self


class DecisionReference(BaseModel):
    """Reference one evaluated decision without reproducing private state."""

    model_config = ConfigDict(extra="forbid")

    hand_number: int = Field(ge=1, strict=True)
    street: Street
    explanation: _Rationale


class JudgeEvaluation(BaseModel):
    """Validated independent evaluation of one player's tournament decisions."""

    model_config = ConfigDict(extra="forbid")

    decision_quality: ScoredRationale
    strategy_consistency: ScoredRationale
    adaptation: ScoredRationale
    reason_quality: ScoredRationale
    tool_usage: ToolUsageEvaluation
    overall_score: int = Field(ge=1, le=10, strict=True)
    strongest_decision: DecisionReference
    weakest_decision: DecisionReference
    main_improvement: _Rationale


class JudgeOutputError(ValueError):
    """A Judge response did not satisfy its structured evaluation contract."""


@dataclass(slots=True)
class JudgeAttemptRecord:
    """Sanitized record of one bounded Judge invocation."""

    attempt: int
    category: str
    error: str | None
    usage: dict[str, int | bool | None]
    retry: bool
