"""Tests for tournament setup, positions, blinds, and button rotation."""

import unittest

from task_3.pokermind.core.domain import (
    PlayerName,
    TournamentStatus,
)
from task_3.pokermind.engine import (
    BLIND_LEVELS,
    assert_chip_invariants,
    blind_for_hand,
    create_tournament,
    positions_for_hand,
    rotate_button,
    setup_next_hand,
)


class TournamentSetupTests(unittest.TestCase):
    def test_fresh_tournament_has_fixed_isolated_state(self) -> None:
        state = create_tournament("tournament-1", seed=42, initial_button_seat=0)
        self.assertEqual(list(state.players), [0, 1, 2])
        self.assertEqual(
            [player.name for player in state.players.values()],
            [
                PlayerName.CONSERVATIVE,
                PlayerName.AGGRESSIVE,
                PlayerName.ADAPTIVE,
            ],
        )
        self.assertEqual([player.stack for player in state.players.values()], [500] * 3)
        self.assertEqual(state.hand_number, 0)
        self.assertIsNone(state.current_hand)
        self.assertTrue(state.peek_available)
        self.assertIsInstance(state.peek_seed, int)
        self.assertIsNone(state.adaptive_peek_observation)
        self.assertEqual(state.status, TournamentStatus.IN_PROGRESS)
        self.assertIsNone(state.failure)
        self.assertEqual(
            state.public_stats,
            {
                name: {
                    "decisions": 0,
                    "folds": 0,
                    "checks": 0,
                    "calls": 0,
                    "raises": 0,
                    "all_ins": 0,
                    "voluntary_chips": 0,
                    "recent_actions": [],
                }
                for name in PlayerName
            },
        )

    def test_initial_buttons_can_rotate_across_three_tournaments(self) -> None:
        states = [create_tournament(str(seat), 7, seat) for seat in range(3)]
        self.assertEqual([state.button_seat for state in states], [0, 1, 2])


class PositionTests(unittest.TestCase):
    def test_three_player_positions_for_every_initial_button(self) -> None:
        expected = {
            0: {
                "button": 0,
                "small_blind": 1,
                "big_blind": 2,
                "preflop_first": 0,
                "postflop_first": 1,
            },
            1: {
                "button": 1,
                "small_blind": 2,
                "big_blind": 0,
                "preflop_first": 1,
                "postflop_first": 2,
            },
            2: {
                "button": 2,
                "small_blind": 0,
                "big_blind": 1,
                "preflop_first": 2,
                "postflop_first": 0,
            },
        }
        for button, positions in expected.items():
            with self.subTest(button=button):
                state = create_tournament("three-handed", 1, button)
                self.assertEqual(positions_for_hand(state), positions)

    def test_heads_up_button_is_small_blind_for_every_survivor_pair(self) -> None:
        survivor_pairs = ((0, 1), (0, 2), (1, 2))
        for survivors in survivor_pairs:
            for button in survivors:
                with self.subTest(survivors=survivors, button=button):
                    state = create_tournament("heads-up", 1, button)
                    eliminated = ({0, 1, 2} - set(survivors)).pop()
                    state.players[eliminated].stack = 0
                    state.players[eliminated].eliminated = True
                    other = next(seat for seat in survivors if seat != button)
                    self.assertEqual(
                        positions_for_hand(state),
                        {
                            "button": button,
                            "small_blind": button,
                            "big_blind": other,
                            "preflop_first": button,
                            "postflop_first": other,
                        },
                    )

    def test_button_rotation_skips_eliminated_seat(self) -> None:
        state = create_tournament("rotate", 1, initial_button_seat=0)
        state.players[1].stack = 0
        state.players[1].eliminated = True
        self.assertEqual(rotate_button(state), 2)
        self.assertEqual(rotate_button(state), 0)


class BlindTests(unittest.TestCase):
    def test_full_blind_schedule_and_final_level_cap(self) -> None:
        expected = [level for level in BLIND_LEVELS for _ in range(2)]
        expected.extend([BLIND_LEVELS[-1]] * (24 - len(expected)))
        actual = [blind_for_hand(hand) for hand in range(1, 25)]
        self.assertEqual(actual, expected)
        self.assertEqual(blind_for_hand(1), (25, 50))
        self.assertEqual(blind_for_hand(2), (25, 50))
        self.assertEqual(blind_for_hand(3), (75, 100))
        self.assertEqual(blind_for_hand(11), (700, 1000))
        self.assertEqual(blind_for_hand(12), (700, 1000))
        self.assertEqual(blind_for_hand(13), (1000, 1500))
        self.assertEqual(blind_for_hand(100), (1000, 1500))

    def test_ordinary_blinds_preserve_all_chip_invariants(self) -> None:
        state = create_tournament("ordinary", 1, initial_button_seat=0)
        hand = setup_next_hand(state)
        self.assertEqual(hand.pot, 75)
        self.assertEqual(
            [player.stack for player in state.players.values()], [500, 475, 450]
        )
        self.assertEqual(
            [player.hand_contribution for player in state.players.values()],
            [0, 25, 50],
        )
        self.assertEqual(
            sum(player.stack for player in state.players.values()) + hand.pot, 1500
        )
        self.assertEqual(
            hand.pot,
            sum(player.hand_contribution for player in state.players.values()),
        )
        assert_chip_invariants(state)

    def test_partial_blind_never_makes_stack_negative(self) -> None:
        state = create_tournament("partial", 1, initial_button_seat=0)
        state.players[0].stack = 990
        state.players[1].stack = 10
        hand = setup_next_hand(state)

        self.assertEqual(state.players[1].stack, 0)
        self.assertTrue(state.players[1].all_in)
        self.assertEqual(hand.pot, 20)
        self.assertEqual(hand.forced_blinds[0]["required"], 25)
        self.assertEqual(hand.forced_blinds[0]["posted"], 10)
        self.assertEqual(hand.forced_blinds[0]["stack_before"], 10)
        self.assertEqual(hand.forced_blinds[0]["stack_after"], 0)
        self.assertEqual(hand.all_in_cap, 10)
        self.assertEqual(hand.refund_events[0]["amount"], 40)
        self.assertEqual(
            sum(player.stack for player in state.players.values()) + hand.pot, 1500
        )
        self.assertEqual(
            hand.pot,
            sum(player.hand_contribution for player in state.players.values()),
        )
        assert_chip_invariants(state)
