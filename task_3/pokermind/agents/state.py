"""Construction of information-isolated player state."""

import copy

from task_3.pokermind.core.domain import PlayerName, TournamentState
from task_3.pokermind.engine import legal_actions

_STRATEGY_PROMPTS = {
    PlayerName.CONSERVATIVE: (
        "Play a patient, lower-variance strategy, but do not fold automatically "
        "before the flop. When you have already posted a blind and the legal call "
        "is affordable relative to your stack, it is often worthwhile to continue "
        "and see the first three community cards. After the flop, reassess the hand: "
        "check when legal with a marginal holding, fold weak holdings when facing "
        "meaningful pressure, and commit larger amounts only with strong evidence. "
        "In heads-up play, normally call the small remaining blind difference when it "
        "is affordable instead of repeatedly surrendering the button."
    ),
    PlayerName.AGGRESSIVE: (
        "Play a controlled aggressive strategy. Apply pressure with legal raises more "
        "often than a cautious player, especially when position, stack size, and prior "
        "checks suggest weakness. Do not raise blindly: fold when the visible evidence "
        "and price are clearly unfavorable, and keep every amount within the supplied "
        "legal range. In heads-up play, normally call an affordable remaining blind "
        "difference rather than repeatedly surrendering the button; apply pressure "
        "after entering the hand."
    ),
    PlayerName.ADAPTIVE: (
        "Play an adaptive strategy based on the current visible state. Use your "
        "opponent-statistics tool when public behavior can improve the decision, and "
        "use the one-time card peek selectively when its information is valuable. "
        "Adjust between folding, calling, checking, and raising from observed current-"
        "tournament tendencies without assuming hidden information. In heads-up play, "
        "normally call an affordable remaining blind difference instead of repeatedly "
        "surrendering the button, then adapt from the flop and public behavior."
    ),
}


def strategy_prompt_summary(player: PlayerName) -> str:
    """Return the fixed observable strategy instruction for one player."""
    return _STRATEGY_PROMPTS[player]


def _serialize_legal_actions(
    state: TournamentState, actor: int
) -> list[dict[str, object]]:
    return [
        {
            "action": action.action.value,
            "amount": action.amount,
            "min_amount": action.min_amount,
            "max_amount": action.max_amount,
        }
        for action in legal_actions(state, actor)
    ]


def _public_action_history(state: TournamentState) -> list[dict[str, int | str]]:
    hand = state.current_hand
    if hand is None:
        return []
    public_fields = ("seat", "player", "street", "action", "amount")
    return [
        {key: action[key] for key in public_fields if key in action}
        for action in hand.action_history
    ]


def build_visible_state(state: TournamentState, actor: int) -> dict[str, object]:
    """Build a new JSON-compatible state containing only actor-visible information."""
    hand = state.current_hand
    if hand is None:
        raise ValueError("No hand is active.")
    if actor not in state.players:
        raise ValueError(f"Unknown physical seat {actor!r}.")

    acting_player = state.players[actor]
    visible: dict[str, object] = {
        "tournament_id": state.tournament_id,
        "hand_number": hand.hand_number,
        "street": hand.street.value,
        "blinds": {"small": hand.small_blind, "big": hand.big_blind},
        "positions": {
            "button": hand.button_seat,
            "small_blind": hand.small_blind_seat,
            "big_blind": hand.big_blind_seat,
        },
        "acting_player": {"seat": actor, "name": acting_player.name.value},
        "hole_cards": [card.short_name() for card in acting_player.hole_cards],
        "board": [card.short_name() for card in hand.board],
        "pot": hand.pot,
        "players": {
            str(seat): {
                "name": player.name.value,
                "stack": player.stack,
                "street_contribution": player.street_contribution,
                "hand_contribution": player.hand_contribution,
                "folded": player.folded,
                "eliminated": player.eliminated,
            }
            for seat, player in sorted(state.players.items())
        },
        "action_history": _public_action_history(state),
        "legal_actions": _serialize_legal_actions(state, actor),
    }
    if (
        acting_player.name is PlayerName.ADAPTIVE
        and state.adaptive_peek_observation is not None
    ):
        visible["peek_observation"] = copy.deepcopy(state.adaptive_peek_observation)
    return visible
