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
    advance_street,
    complete_uncontested_hand,
    create_tournament,
    hand_seed,
    resolve_showdown,
    start_hand,
)


def parsed_cards(codes: str) -> list[Card]:
    return [Card.parse(code) for code in codes.split()]


class HandLifecycleTests(unittest.TestCase):
    def _check_around(self, state: TournamentState, actors: tuple[int, ...]) -> None:
        for actor in actors:
            apply_action(state, actor, ActionDecision(ActionType.CHECK, 0))

    def _set_showdown_cards(
        self,
        state: TournamentState,
        hole_cards: dict[int, str],
        board: str,
    ) -> None:
        hand = state.current_hand
        if hand is None:
            self.fail("Test fixture requires an active hand.")
        hand.deck = []
        hand.board = parsed_cards(board)
        hand.street = Street.SHOWDOWN
        for seat, codes in hole_cards.items():
            state.players[seat].hole_cards = parsed_cards(codes)

    def test_start_hand_is_seeded_and_deals_without_duplicates(self) -> None:
        first = create_tournament("first", 2026, 0)
        second = create_tournament("second", 2026, 0)
        first_hand = start_hand(first)
        second_hand = start_hand(second)

        self.assertEqual(first_hand.hand_seed, hand_seed(2026, 1))
        self.assertEqual(first_hand.deck, second_hand.deck)
        self.assertEqual(
            [player.hole_cards for player in first.players.values()],
            [player.hole_cards for player in second.players.values()],
        )
        all_cards = [
            *first_hand.deck,
            *(card for player in first.players.values() for card in player.hole_cards),
        ]
        self.assertEqual(len(all_cards), 52)
        self.assertEqual(len(set(all_cards)), 52)

    def test_fold_preflop_awards_without_dealing_flop(self) -> None:
        state = create_tournament("fold-win", 3, 0)
        state.players[0].stack = 1000
        state.players[2].stack = 0
        state.players[2].eliminated = True
        hand = start_hand(state)

        self.assertEqual(hand.pending_to_act, [0, 1])
        apply_action(state, 0, ActionDecision(ActionType.FOLD, 0))

        self.assertTrue(hand.completed)
        self.assertEqual(hand.board, [])
        self.assertEqual(hand.winner_seats, [1])
        self.assertEqual(hand.pot_awards, {1: 75})
        self.assertEqual([state.players[0].stack, state.players[1].stack], [975, 525])
        self.assertEqual(state.button_seat, 1)
        self.assertEqual(sum(player.stack for player in state.players.values()), 1500)
        with self.assertRaisesRegex(ValueError, "completed twice"):
            complete_uncontested_hand(state)

    def test_normal_hand_deals_board_in_exact_street_sequence(self) -> None:
        state = create_tournament("streets", 4, 0)
        hand = start_hand(state)
        self.assertEqual(len(hand.board), 0)

        apply_action(state, 0, ActionDecision(ActionType.CALL, 50))
        apply_action(state, 1, ActionDecision(ActionType.CALL, 25))
        apply_action(state, 2, ActionDecision(ActionType.CHECK, 0))
        self.assertEqual(advance_street(state), Street.FLOP)
        self.assertEqual(len(hand.board), 3)
        self.assertEqual(
            [player.street_contribution for player in state.players.values()],
            [0, 0, 0],
        )

        self._check_around(state, (1, 2, 0))
        self.assertEqual(advance_street(state), Street.TURN)
        self.assertEqual(len(hand.board), 4)
        self._check_around(state, (1, 2, 0))
        self.assertEqual(advance_street(state), Street.RIVER)
        self.assertEqual(len(hand.board), 5)
        self._check_around(state, (1, 2, 0))
        self.assertEqual(advance_street(state), Street.SHOWDOWN)

        self.assertTrue(hand.completed)
        self.assertEqual(len(hand.board), 5)
        self.assertEqual(hand.pot, 0)
        self.assertTrue(hand.winner_seats)
        self.assertTrue(
            all(player.hand_contribution == 0 for player in state.players.values())
        )
        self.assertEqual(sum(player.stack for player in state.players.values()), 1500)

    def test_known_stronger_hand_receives_full_pot(self) -> None:
        state = create_tournament("stronger", 5, 0)
        hand = start_hand(state)
        self._set_showdown_cards(
            state,
            {0: "As Ad", 1: "Kc Kd", 2: "Qc Qd"},
            "2s 3s 4h 8d 9c",
        )

        self.assertEqual(resolve_showdown(state), [0])
        self.assertEqual(hand.pot_awards, {0: 75})
        self.assertEqual(hand.showdown_results[0]["category"], "pair")
        self.assertEqual(hand.winning_rank, (1, 14, 9, 8, 4))

    def test_tie_split_and_odd_chips_start_left_of_button(self) -> None:
        state = create_tournament("tie", 6, 0)
        hand = start_hand(state)
        self._set_showdown_cards(
            state,
            {0: "2c 3d", 1: "4c 5d", 2: "6c 7d"},
            "As Ks Qs Js Ts",
        )
        state.players[0].stack -= 1
        state.players[0].hand_contribution += 1
        state.players[0].street_contribution += 1
        hand.pot += 1

        self.assertEqual(resolve_showdown(state), [0, 1, 2])
        self.assertEqual(hand.pot_awards, {0: 25, 1: 26, 2: 25})
        self.assertEqual(hand.odd_chip_order, [1])
        self.assertEqual(hand.winning_rank, (9, 14))
        self.assertEqual(sum(player.stack for player in state.players.values()), 1500)

    def test_folded_player_is_not_showdown_eligible(self) -> None:
        state = create_tournament("folded", 7, 0)
        hand = start_hand(state)
        self._set_showdown_cards(
            state,
            {0: "As Ad", 1: "Kc Kd", 2: "Qc Qd"},
            "2s 3s 4h 8d 9c",
        )
        state.players[0].folded = True

        self.assertEqual(resolve_showdown(state), [1])
        self.assertNotIn(0, hand.showdown_results)
        self.assertEqual(hand.pot_awards, {1: 75})

    def test_showdown_cannot_award_or_reset_twice(self) -> None:
        state = create_tournament("once", 8, 0)
        hand = start_hand(state)
        self._set_showdown_cards(
            state,
            {0: "As Ad", 1: "Kc Kd", 2: "Qc Qd"},
            "2s 3s 4h 8d 9c",
        )
        resolve_showdown(state)
        stacks = [player.stack for player in state.players.values()]

        with self.assertRaisesRegex(ValueError, "completed twice"):
            resolve_showdown(state)
        self.assertEqual([player.stack for player in state.players.values()], stacks)
        self.assertEqual(hand.pot, 0)
        self.assertTrue(
            all(player.hand_contribution == 0 for player in state.players.values())
        )
