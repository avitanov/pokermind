"""Atomic JSON snapshot and experiment-summary persistence."""

import json
import logging
import os
import tempfile
from pathlib import Path

from task_3.pokermind.core.domain import TournamentStatus

LOGGER = logging.getLogger(__name__)


class ResultWriteError(OSError):
    """An atomic tournament snapshot could not be written."""


class SnapshotLoadError(ValueError):
    """A tournament snapshot could not be loaded for continuation."""


def _safe_tournament_id(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Tournament result requires a non-empty tournament ID.")
    if any(
        character
        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for character in value
    ):
        raise ValueError("Tournament ID may contain only letters, digits, '-' and '_'.")
    return value


def _write_json_atomic(payload: dict[str, object], target: Path) -> None:
    temporary_path: Path | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(target)
    except (OSError, TypeError, ValueError) as error:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise ResultWriteError(f"Could not write JSON snapshot {target}.") from error


def write_snapshot(result: dict[str, object], output_directory: Path) -> Path:
    """Atomically write an in-progress or completed tournament JSON snapshot."""
    tournament_id = _safe_tournament_id(result.get("tournament_id"))
    completed = result.get("status") == TournamentStatus.COMPLETED.value
    filename = (
        f"tournament_{tournament_id}.json"
        if completed
        else f"tournament_{tournament_id}.in_progress.json"
    )
    target = output_directory / filename
    _write_json_atomic(result, target)

    if completed:
        in_progress = output_directory / f"tournament_{tournament_id}.in_progress.json"
        try:
            in_progress.unlink(missing_ok=True)
        except OSError as error:
            LOGGER.warning(
                "Final snapshot written but stale in-progress snapshot could not be removed: %s",
                type(error).__name__,
            )
    LOGGER.info("Tournament snapshot written to %s", target)
    return target


def load_snapshot(path: Path) -> dict[str, object]:
    """Load a tournament snapshot without changing or deleting it."""
    try:
        with path.open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        raise SnapshotLoadError(
            f"Could not load tournament snapshot {path}."
        ) from error
    if not isinstance(payload, dict):
        raise SnapshotLoadError("Tournament snapshot root must be a JSON object.")
    return payload


def write_experiment_summary(
    summary: dict[str, object], output_directory: Path
) -> Path:
    """Atomically persist the deterministic three-tournament aggregation."""
    target = output_directory / "experiment_summary.json"
    _write_json_atomic(summary, target)
    LOGGER.info("Experiment summary written to %s", target)
    return target
