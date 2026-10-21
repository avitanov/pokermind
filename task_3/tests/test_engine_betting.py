"""Tests for tournament setup, positions, blinds, and button rotation."""

from copy import deepcopy
import unittest

from task_3.pokermind.core.domain import (
    ActionDecision,
    ActionType,
    Street,
)
from task_3.pokermind.engine import (
    ActionValidationError,
    apply_action,
    assert_chip_invariants,
    create_tournament,
    initialize_betting_round,
    legal_actions,
    setup_next_hand,
    validate_action,
)


class BettingRoundTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = create_tournament("betting", 11, initial_button_seat=0)
        self.hand = setup_next_hand(self.state)

    def test_preflop_fold_call_check_completes_once(self) -> None:
        self.assertEqual(self.hand.pending_to_act, [0, 1, 2])
        apply_action(self.state, 0, ActionDecision(ActionType.FOLD, 0))
        apply_action(self.state, 1, ActionDecision(ActionType.CALL, 25))
        apply_action(self.state, 2, ActionDecision(ActionType.CHECK, 0))

        self.assertTrue(self.hand.round_complete)
        self.assertEqual(self.hand.pending_to_act, [])
        self.assertEqual(self.hand.pot, 100)
        self.assertEqual(
            [player.street_contribution for player in self.state.players.values()],
            [0, 50, 50],
        )
        self.assertEqual(len(self.hand.action_history), 3)
        with self.assertRaises(ActionValidationError):
            apply_action(self.state, 2, ActionDecision(ActionType.CHECK, 0))

    def test_raise_rebuilds_queue_in_clockwise_order(self) -> None:
        actions = legal_actions(self.state, 0)
        raise_action = next(
            action for action in actions if action.action is ActionType.RAISE
        )
        self.assertEqual((raise_action.min_amount, raise_action.max_amount), (100, 500))

        apply_action(self.state, 0, ActionDecision(ActionType.RAISE, 100))
        self.assertEqual(self.hand.current_bet, 100)
        self.assertEqual(self.hand.last_full_raise_size, 50)
        self.assertEqual(self.hand.pending_to_act, [1, 2])

        next_raise = next(
            action
            for action in legal_actions(self.state, 1)
            if action.action is ActionType.RAISE
        )
        self.assertEqual((next_raise.min_amount, next_raise.max_amount), (125, 475))
        apply_action(self.state, 1, ActionDecision(ActionType.RAISE, 125))
        self.assertEqual(self.hand.current_bet, 150)
        self.assertEqual(self.hand.last_full_raise_size, 50)
        self.assertEqual(self.hand.pending_to_act, [2, 0])

    def test_postflop_check_around_moves_no_chips(self) -> None:
        starting_stacks = [player.stack for player in self.state.players.values()]
        starting_pot = self.hand.pot
        self.hand.street = Street.FLOP
        for player in self.state.players.values():
            player.street_contribution = 0
        initialize_betting_round(self.state, self.hand.postflop_first_seat)
        self.assertEqual(self.hand.pending_to_act, [1, 2, 0])

        for actor in (1, 2, 0):
            apply_action(self.state, actor, ActionDecision(ActionType.CHECK, 0))

        self.assertTrue(self.hand.round_complete)
        self.assertEqual(
            [player.stack for player in self.state.players.values()], starting_stacks
        )
        self.assertEqual(self.hand.pot, starting_pot)
        assert_chip_invariants(self.state)

    def test_invalid_actions_and_amounts_do_not_mutate_state(self) -> None:
        invalid_cases = (
            (1, ActionDecision(ActionType.CALL, 10)),
            (0, ActionDecision(ActionType.CHECK, 0)),
            (0, ActionDecision(ActionType.CALL, 24)),
            (0, ActionDecision(ActionType.CALL, -1)),
            (0, ActionDecision(ActionType.RAISE, 49)),
            (0, ActionDecision(ActionType.RAISE, 501)),
        )
        for actor, decision in invalid_cases:
            with self.subTest(actor=actor, decision=decision):
                before = deepcopy(self.state)
                self.assertTrue(validate_action(self.state, actor, decision))
                self.assertEqual(self.state, before)
                with self.assertRaises(ActionValidationError):
                    apply_action(self.state, actor, decision)
                self.assertEqual(self.state, before)

    def test_fold_is_illegal_when_checking_costs_nothing(self) -> None:
        self.hand.street = Street.FLOP
        for player in self.state.players.values():
            player.street_contribution = 0
        initialize_betting_round(self.state, 1)
        self.assertTrue(
            validate_action(self.state, 1, ActionDecision(ActionType.FOLD, 0))
        )

    def test_short_all_in_raise_is_identified_but_not_resolved(self) -> None:
        self.state.players[0].stack = 70
        self.state.players[1].stack += 430
        action = next(
            action
            for action in legal_actions(self.state, 0)
            if action.action is ActionType.RAISE
        )
        self.assertEqual((action.min_amount, action.max_amount), (70, 70))
        apply_action(self.state, 0, ActionDecision(ActionType.RAISE, 70))
        self.assertTrue(self.state.players[0].all_in)
        self.assertEqual(self.hand.current_bet, 70)
        self.assertEqual(self.hand.last_full_raise_size, 50)
        self.assertEqual(self.hand.pending_to_act, [1, 2])
        assert_chip_invariants(self.state)

    def test_every_accepted_action_preserves_chip_invariants(self) -> None:
        sequence = (
            (0, ActionDecision(ActionType.RAISE, 100)),
            (1, ActionDecision(ActionType.CALL, 75)),
            (2, ActionDecision(ActionType.CALL, 50)),
        )
        for actor, decision in sequence:
            apply_action(self.state, actor, decision)
            assert_chip_invariants(self.state)
        self.assertTrue(self.hand.round_complete)
        self.assertEqual(self.hand.pot, 300)
