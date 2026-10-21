"""Production orchestration for observation and complete tournament runs."""

import logging
from pathlib import Path

from langfuse import Langfuse
from strands import Agent

from task_3.pokermind.agents import (
    coordinate_decision,
    create_player_agents,
    invoke_player_once,
)
from task_3.pokermind.core.domain import PlayerName, TournamentState, TournamentStatus
from task_3.pokermind.engine import (
    MAX_TOURNAMENT_HANDS,
    TournamentLimitError,
    advance_street,
    assert_chip_invariants,
    create_tournament,
    start_hand,
)
from task_3.pokermind.evaluation import (
    create_judge_client,
    evaluate_player,
    invoke_judge_once,
)
from task_3.pokermind.experiment.validation import (
    _preflight_openrouter,
    _utc_now,
    validate_completed_result,
)
from task_3.pokermind.observability import flush_observability
from task_3.pokermind.results import (
    add_judge_evaluation,
    create_experiment_summary,
    create_tournament_result,
    finalize_tournament_result,
    load_snapshot,
    prepare_resumed_result,
    record_decision,
    record_hand_completion,
    record_hand_progress,
    record_hand_start,
    restore_runtime_checkpoint,
    write_experiment_summary,
    write_snapshot,
)

LOGGER = logging.getLogger(__name__)


def _finalize_failed_tournament(
    result: dict[str, object],
    state: TournamentState,
    output_directory: Path,
) -> Path:
    finalize_tournament_result(result, state, completed_at=_utc_now())
    return write_snapshot(result, output_directory)


def _completed_judge_players(result: dict[str, object]) -> set[str]:
    evaluations = result.get("judge_evaluations")
    if not isinstance(evaluations, list):
        return set()
    return {
        evaluation.get("player")
        for evaluation in evaluations
        if isinstance(evaluation, dict) and evaluation.get("status") == "completed"
    }


def _ensure_judge_evaluations(
    result: dict[str, object],
    output_directory: Path,
    telemetry_client: Langfuse | None,
) -> Path | None:
    """Run only the Judge evaluations not yet completed so a crash mid-judging
    (or an offline rerun of a fully judged tournament) never re-spends calls."""
    completed = _completed_judge_players(result)
    pending = [player for player in PlayerName if player.value not in completed]
    if not pending:
        return None
    _preflight_openrouter()
    judge_client = create_judge_client()
    latest_path: Path | None = None
    for player in pending:
        evaluation = evaluate_player(
            result,
            player,
            lambda prompt, attempt: invoke_judge_once(judge_client, prompt, attempt),
            telemetry_client,
        )
        add_judge_evaluation(result, evaluation)
        latest_path = write_snapshot(result, output_directory)
    return latest_path


def _play_one_agent_hand(
    state: TournamentState,
    result: dict[str, object],
    player_agents: dict[PlayerName, Agent],
    output_directory: Path | None,
    telemetry_client: Langfuse | None,
    *,
    continue_current_hand: bool = False,
) -> Path | None:
    if continue_current_hand:
        hand = state.current_hand
        if hand is None or hand.completed:
            raise ValueError("A resumable tournament requires an active hand.")
    else:
        hand = start_hand(state)
        record_hand_start(result, state)
        if hand.completed:
            # A forced blind can put a short stack all-in and run the board out
            # inside start_hand, completing the hand before anyone acts. Finalize
            # it here (before the snapshot) so it is never persisted unfinished.
            state.counters["hands_completed"] += 1
            record_hand_completion(result, state)
    latest_path = (
        write_snapshot(result, output_directory)
        if output_directory is not None
        else None
    )

    while not hand.completed and state.status is TournamentStatus.IN_PROGRESS:
        if hand.pending_to_act:
            actor = hand.pending_to_act[0]

            def invoke_once(prompt: str, attempt: int) -> object:
                return invoke_player_once(
                    player_agents,
                    state,
                    actor,
                    prompt,
                    attempt,
                )

            outcome = coordinate_decision(
                state,
                actor,
                invoke_once,
                telemetry_client=telemetry_client,
            )
            if not outcome.api_failed:
                state.counters["actions"] += 1
            record_decision(result, state, actor, outcome)
            # Finalize the hand record BEFORE the snapshot: apply_action can end
            # the hand mid-decision, so a snapshot taken here must already carry
            # ending_stacks and the completed-hand counter, or a crash would
            # persist a "completed" hand the resume path can never repair.
            if hand.completed:
                state.counters["hands_completed"] += 1
                record_hand_completion(result, state)
            if output_directory is not None:
                latest_path = write_snapshot(result, output_directory)
            assert_chip_invariants(state)
            if outcome.api_failed:
                return latest_path
        elif hand.round_complete:
            advance_street(state)
            if hand.completed:
                state.counters["hands_completed"] += 1
                record_hand_completion(result, state)
                if output_directory is not None:
                    latest_path = write_snapshot(result, output_directory)
            else:
                record_hand_progress(result, state)
            assert_chip_invariants(state)
        else:
            raise AssertionError("An active hand has no actor or completed round.")

    return latest_path


def run_observation_hand(
    tournament_id: str,
    seed: int,
    initial_button: int,
    telemetry_client: Langfuse | None = None,
) -> tuple[TournamentState, dict[str, object]]:
    """Run one real agent-driven hand through the production decision path."""
    _preflight_openrouter()
    player_agents = create_player_agents()
    state = create_tournament(tournament_id, seed, initial_button)
    result = create_tournament_result(state, started_at=_utc_now())
    _play_one_agent_hand(
        state,
        result,
        player_agents,
        None,
        telemetry_client,
    )
    return state, result


def run_one_tournament(
    tournament_id: str,
    seed: int,
    initial_button: int,
    output_directory: Path,
    telemetry_client: Langfuse | None = None,
) -> tuple[TournamentState, dict[str, object], Path]:
    """Run one fresh production tournament, its Judges, snapshots, and replay gate."""
    _preflight_openrouter()
    player_agents = create_player_agents()
    state = create_tournament(tournament_id, seed, initial_button)
    result = create_tournament_result(state, started_at=_utc_now())
    return _continue_tournament(
        state,
        result,
        player_agents,
        output_directory,
        telemetry_client,
    )


def _continue_tournament(
    state: TournamentState,
    result: dict[str, object],
    player_agents: dict[PlayerName, Agent],
    output_directory: Path,
    telemetry_client: Langfuse | None,
    *,
    resume_active_hand: bool = False,
) -> tuple[TournamentState, dict[str, object], Path]:
    latest_path: Path | None = write_snapshot(result, output_directory)
    continue_current_hand = resume_active_hand

    while state.status is TournamentStatus.IN_PROGRESS:
        if state.counters["hands_completed"] >= MAX_TOURNAMENT_HANDS:
            raise TournamentLimitError(state)
        latest_path = _play_one_agent_hand(
            state,
            result,
            player_agents,
            output_directory,
            telemetry_client,
            continue_current_hand=continue_current_hand,
        )
        continue_current_hand = False
        if state.status is TournamentStatus.FAILED:
            latest_path = _finalize_failed_tournament(result, state, output_directory)
            flush_observability(telemetry_client)
            return state, result, latest_path

    if state.status is not TournamentStatus.COMPLETED:
        latest_path = _finalize_failed_tournament(result, state, output_directory)
        flush_observability(telemetry_client)
        return state, result, latest_path

    finalize_tournament_result(result, state, completed_at=_utc_now())
    latest_path = write_snapshot(result, output_directory)
    judged_path = _ensure_judge_evaluations(result, output_directory, telemetry_client)
    if judged_path is not None:
        latest_path = judged_path

    validate_completed_result(result)
    flush_observability(telemetry_client)
    if latest_path is None:
        raise AssertionError("A completed tournament must have a snapshot path.")
    LOGGER.info("Tournament %s passed the integration gate", state.tournament_id)
    return state, result, latest_path


def resume_tournament(
    snapshot_path: Path,
    output_directory: Path | None = None,
    telemetry_client: Langfuse | None = None,
) -> tuple[TournamentState, dict[str, object], Path]:
    """Continue a failed or interrupted tournament from its atomic checkpoint."""
    _preflight_openrouter()
    result = load_snapshot(snapshot_path)
    state = restore_runtime_checkpoint(result)
    if state.status is TournamentStatus.COMPLETED:
        # Crash between the tournament-ending action and finalization: the file
        # was still named in-progress, but play is already over. Do not replay a
        # hand (and do not refuse it) — let _continue_tournament finalize, judge,
        # and validate it into the completed file.
        resume_active_hand = False
    else:
        # IN_PROGRESS or FAILED: prepare_resumed_result resets a failed run back
        # to in-progress so the interrupted decision is retried from its snapshot.
        prepare_resumed_result(result, state)
        current_hand = state.current_hand
        resume_active_hand = current_hand is not None and not current_hand.completed
    player_agents = create_player_agents()
    return _continue_tournament(
        state,
        result,
        player_agents,
        output_directory or snapshot_path.parent,
        telemetry_client,
        resume_active_hand=resume_active_hand,
    )


def _validate_saved_identity(
    result: dict[str, object],
    tournament_id: str,
    seed: int,
    initial_button: int,
) -> None:
    expected = (tournament_id, seed, initial_button)
    actual = (
        result.get("tournament_id"),
        result.get("seed"),
        result.get("initial_button"),
    )
    if actual != expected:
        raise ValueError("Saved tournament identity does not match the requested run.")


def run_or_resume_tournament(
    tournament_id: str,
    seed: int,
    initial_button: int,
    output_directory: Path,
    telemetry_client: Langfuse | None = None,
) -> tuple[TournamentState, dict[str, object], Path]:
    """Reuse a completed run, resume its checkpoint, or start it fresh."""
    completed_path = output_directory / f"tournament_{tournament_id}.json"
    in_progress_path = output_directory / f"tournament_{tournament_id}.in_progress.json"
    if completed_path.exists():
        result = load_snapshot(completed_path)
        _validate_saved_identity(result, tournament_id, seed, initial_button)
        # Poker play is durably complete; a crash may have interrupted the Judge
        # phase. Finish only the missing evaluations instead of replaying the hand.
        judged_path = _ensure_judge_evaluations(
            result, output_directory, telemetry_client
        )
        state = validate_completed_result(result)
        LOGGER.info("Reusing completed tournament %s", tournament_id)
        return state, result, judged_path or completed_path
    if in_progress_path.exists():
        result = load_snapshot(in_progress_path)
        _validate_saved_identity(result, tournament_id, seed, initial_button)
        LOGGER.info("Resuming tournament %s from its last snapshot", tournament_id)
        return resume_tournament(
            in_progress_path,
            output_directory,
            telemetry_client,
        )
    return run_one_tournament(
        tournament_id,
        seed,
        initial_button,
        output_directory,
        telemetry_client,
    )


def run_final_experiment(
    base_seed: int,
    output_directory: Path,
    telemetry_client: Langfuse | None = None,
) -> tuple[list[Path], dict[str, object], Path]:
    """Run the fixed three isolated tournaments and aggregate their JSON files."""
    tournament_paths: list[Path] = []
    for index, initial_button in enumerate((0, 1, 2)):
        seed = base_seed + index
        tournament_id = f"final_{index + 1}_{seed}_button_{initial_button}"
        _, result, path = run_or_resume_tournament(
            tournament_id,
            seed,
            initial_button,
            output_directory,
            telemetry_client,
        )
        if result.get("status") != TournamentStatus.COMPLETED.value:
            raise RuntimeError(f"Final tournament {index + 1} did not complete.")
        tournament_paths.append(path)

    summary = create_experiment_summary(tournament_paths, base_seed)
    summary_path = write_experiment_summary(summary, output_directory)
    return tournament_paths, summary, summary_path
