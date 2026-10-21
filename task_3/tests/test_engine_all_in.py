"""Tests for tournament setup, positions, blinds, and button rotation."""

import unittest

from task_3.pokermind.core.domain import (
    ActionDecision,
    ActionType,
    Card,
    Street,
    TournamentState,
)
from task_3.pokermind.engine import (
    apply_action,
    assert_chip_invariants,
    advance_street,
    create_tournament,
    legal_actions,
    positions_for_hand,
    resolve_showdown,
    start_hand,
)


def parsed_cards(codes: str) -> list[Card]:
    return [Card.parse(code) for code in codes.split()]


class AllInResolutionTests(unittest.TestCase):
    def _configure_betting_state(
        self,
        state: TournamentState,
        contributions: tuple[int, int, int],
        stacks: tuple[int, int, int],
        pending: list[int],
    ) -> None:
        hand = state.current_hand
        if hand is None:
            self.fail("Test fixture requires an active hand.")
        hand.pot = sum(contributions)
        hand.current_bet = max(contributions)
        hand.last_full_raise_size = hand.big_blind
        hand.pending_to_act = pending
        hand.round_complete = False
        hand.all_in_resolution = False
        hand.all_in_cap = None
        for seat, player in state.players.items():
            player.stack = stacks[seat]
            player.hand_contribution = contributions[seat]
            player.street_contribution = contributions[seat]
            player.folded = False
            player.all_in = False
            player.eliminated = False
        assert_chip_invariants(state)

    def _call_until_complete(self, state: TournamentState) -> None:
        hand = state.current_hand
        if hand is None:
            self.fail("Test fixture requires an active hand.")
        while not hand.completed:
            actor = hand.pending_to_act[0]
            call = next(
                action
                for action in legal_actions(state, actor)
                if action.action is ActionType.CALL
            )
            apply_action(
                state,
                actor,
                ActionDecision(ActionType.CALL, call.amount or 0),
            )

    def test_scenario_a_short_all_in_reaches_common_cap(self) -> None:
        state = create_tournament("scenario-a", 21, 0)
        hand = start_hand(state)
        self._configure_betting_state(
            state,
            contributions=(50, 50, 50),
            stacks=(100, 625, 625),
            pending=[0, 1, 2],
        )

        apply_action(state, 0, ActionDecision(ActionType.RAISE, 100))
        self.assertEqual(hand.all_in_cap, 150)
        self.assertEqual(hand.pending_to_act, [1, 2])
        self._call_until_complete(state)

        self.assertEqual(hand.all_in_final_contributions, {0: 150, 1: 150, 2: 150})
        self.assertEqual(sum(hand.pot_awards.values()), 450)
        self.assertEqual(hand.refund_events, [])
        self.assertEqual(sum(player.stack for player in state.players.values()), 1500)

    def test_scenario_b_short_caller_lowers_cap_and_refunds_excess(self) -> None:
        state = create_tournament("scenario-b", 22, 0)
        hand = start_hand(state)
        self._configure_betting_state(
            state,
            contributions=(50, 50, 400),
            stacks=(350, 200, 450),
            pending=[0, 1],
        )

        apply_action(state, 0, ActionDecision(ActionType.CALL, 350))
        apply_action(state, 1, ActionDecision(ActionType.CALL, 200))

        self.assertTrue(hand.completed)
        self.assertEqual(hand.all_in_cap, 250)
        self.assertEqual(hand.all_in_final_contributions, {0: 250, 1: 250, 2: 250})
        self.assertEqual(
            [(event["seat"], event["amount"]) for event in hand.refund_events],
            [(0, 150), (2, 150)],
        )
        self.assertEqual(sum(hand.pot_awards.values()), 750)

    def test_scenario_c_folded_contribution_remains_dead(self) -> None:
        state = create_tournament("scenario-c", 23, 0)
        hand = start_hand(state)
        self._configure_betting_state(
            state,
            contributions=(50, 50, 300),
            stacks=(150, 500, 450),
            pending=[0, 1],
        )
        state.players[2].folded = True
        hand.current_bet = 50

        apply_action(state, 0, ActionDecision(ActionType.RAISE, 150))
        apply_action(state, 1, ActionDecision(ActionType.CALL, 150))

        self.assertEqual(hand.all_in_final_contributions, {0: 200, 1: 200})
        self.assertEqual(sum(hand.pot_awards.values()), 700)
        self.assertFalse(any(event["seat"] == 2 for event in hand.refund_events))

    def test_forced_blind_all_in_refunds_and_runs_out(self) -> None:
        state = create_tournament("blind-all-in", 24, 0)
        state.players[0].stack = 10
        state.players[1].stack = 1490
        state.players[2].stack = 0
        state.players[2].eliminated = True

        hand = start_hand(state)

        self.assertTrue(hand.completed)
        self.assertEqual(hand.all_in_cap, 10)
        self.assertEqual(hand.all_in_final_contributions, {0: 10, 1: 10})
        self.assertEqual(hand.refund_events[0]["seat"], 1)
        self.assertEqual(hand.refund_events[0]["amount"], 40)
        self.assertEqual(len(hand.board), 5)
        self.assertEqual(sum(player.stack for player in state.players.values()), 1500)

    def test_opponent_can_fold_during_all_in_resolution(self) -> None:
        state = create_tournament("resolution-fold", 25, 0)
        hand = start_hand(state)
        self._configure_betting_state(
            state,
            contributions=(50, 50, 50),
            stacks=(100, 625, 625),
            pending=[0, 1, 2],
        )

        apply_action(state, 0, ActionDecision(ActionType.RAISE, 100))
        apply_action(state, 1, ActionDecision(ActionType.FOLD, 0))
        apply_action(state, 2, ActionDecision(ActionType.CALL, 100))

        self.assertTrue(hand.completed)
        self.assertEqual(sum(hand.pot_awards.values()), 350)
        self.assertTrue(state.players[1].folded)

    def test_all_in_on_every_street_runs_board_out_once(self) -> None:
        targets = (Street.PREFLOP, Street.FLOP, Street.TURN, Street.RIVER)
        for index, target in enumerate(targets):
            with self.subTest(street=target):
                state = create_tournament(f"street-{target.value}", 30 + index, 0)
                hand = start_hand(state)
                if target is not Street.PREFLOP:
                    apply_action(state, 0, ActionDecision(ActionType.CALL, 50))
                    apply_action(state, 1, ActionDecision(ActionType.CALL, 25))
                    apply_action(state, 2, ActionDecision(ActionType.CHECK, 0))
                while hand.street is not target:
                    advance_street(state)
                    if hand.street is target:
                        break
                    for actor in tuple(hand.pending_to_act):
                        apply_action(state, actor, ActionDecision(ActionType.CHECK, 0))

                actor = hand.pending_to_act[0]
                receiver = next(seat for seat in state.players if seat != actor)
                transfer = state.players[actor].stack - 50
                state.players[actor].stack = 50
                state.players[receiver].stack += transfer
                action = (
                    ActionType.CALL if target is Street.PREFLOP else ActionType.RAISE
                )
                apply_action(state, actor, ActionDecision(action, 50))
                self._call_until_complete(state)

                self.assertEqual(len(hand.board), 5)
                self.assertTrue(hand.completed)
                self.assertEqual(hand.street, Street.SHOWDOWN)
                self.assertEqual(len(set(hand.board)), 5)
                self.assertEqual(
                    sum(player.stack for player in state.players.values()), 1500
                )

    def test_two_eliminations_produce_one_1500_chip_winner(self) -> None:
        state = create_tournament("winner", 40, 0)
        hand = start_hand(state)
        hand.deck = []
        hand.board = parsed_cards("2s 3s 4h 8d 9c")
        hand.street = Street.SHOWDOWN
        hole_cards = {0: "As Ad", 1: "Kc Kd", 2: "Qc Qd"}
        for seat, codes in hole_cards.items():
            state.players[seat].hole_cards = parsed_cards(codes)
            state.players[seat].stack = 0
            state.players[seat].hand_contribution = 500
            state.players[seat].street_contribution = 500
            state.players[seat].all_in = True
        hand.pot = 1500

        self.assertEqual(resolve_showdown(state), [0])
        self.assertTrue(state.completed)
        self.assertEqual(state.winner_seat, 0)
        self.assertEqual(state.players[0].stack, 1500)
        self.assertEqual(hand.eliminated_seats, [1, 2])

    def test_one_elimination_transitions_to_heads_up_positions(self) -> None:
        state = create_tournament("heads-up-transition", 41, 0)
        hand = start_hand(state)
        hand.deck = []
        hand.board = parsed_cards("2s 3s 4h 8d 9c")
        hand.street = Street.SHOWDOWN
        hole_cards = {0: "As Ad", 1: "Kc Kd", 2: "Qc Qd"}
        for seat, codes in hole_cards.items():
            state.players[seat].hole_cards = parsed_cards(codes)
            state.players[seat].hand_contribution = 100
            state.players[seat].street_contribution = 100
        state.players[0].stack = 400
        state.players[1].stack = 800
        state.players[2].stack = 0
        hand.pot = 300

        resolve_showdown(state)

        self.assertTrue(state.players[2].eliminated)
        self.assertFalse(state.completed)
        positions = positions_for_hand(state)
        self.assertEqual(positions["button"], positions["small_blind"])
        self.assertEqual({positions["button"], positions["big_blind"]}, {0, 1})
        self.assertFalse(hasattr(hand, "side_pots"))
