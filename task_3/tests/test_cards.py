"""Deterministic tests for PokerMind cards, decks, and hand ranking."""

import unittest

from task_3.pokermind.core.domain import Card
from task_3.pokermind.engine.cards import Deck, evaluate_seven_cards


def cards(codes: str) -> list[Card]:
    return [Card.parse(code) for code in codes.split()]


class CardTests(unittest.TestCase):
    def test_card_short_name_round_trip(self) -> None:
        for code in "2c 9d Th Js Qc Kh As".split():
            self.assertEqual(Card.parse(code).short_name(), code)

    def test_malformed_card_codes_fail(self) -> None:
        for code in ("", "A", "10s", "1s", "AS", "xs", "Ace"):
            with self.subTest(code=code), self.assertRaises((TypeError, ValueError)):
                Card.parse(code)
        with self.assertRaises(TypeError):
            Card.parse(14)  # type: ignore[arg-type]


class DeckTests(unittest.TestCase):
    def test_deck_has_52_unique_cards(self) -> None:
        deck = Deck(seed=1)
        self.assertEqual(len(deck.cards), 52)
        self.assertEqual(len(set(deck.cards)), 52)

    def test_seeded_order_is_reproducible_and_seed_specific(self) -> None:
        first = Deck(seed=2026).cards
        self.assertEqual(first, Deck(seed=2026).cards)
        self.assertNotEqual(first, Deck(seed=2027).cards)

    def test_deal_removes_exact_cards_in_order(self) -> None:
        deck = Deck(seed=9)
        initial = deck.cards
        self.assertEqual(deck.deal(3), list(initial[:3]))
        self.assertEqual(deck.cards, initial[3:])

    def test_over_dealing_has_actionable_error(self) -> None:
        deck = Deck(seed=2)
        deck.deal(50)
        with self.assertRaisesRegex(ValueError, "only 2 remain"):
            deck.deal(3)
        self.assertEqual(len(deck.cards), 2)


class HandEvaluationTests(unittest.TestCase):
    CATEGORY_HANDS = (
        ("As Kd 9c 7h 4s 3d 2c", (0, 14, 13, 9, 7, 4), "high card"),
        ("As Ad Kc 9h 7s 4d 2c", (1, 14, 13, 9, 7), "pair"),
        ("As Ad Kc Kh 7s 4d 2c", (2, 14, 13, 7), "two pair"),
        ("As Ad Ac Kh 7s 4d 2c", (3, 14, 13, 7), "three of a kind"),
        ("9s 8d 7c 6h 5s 2d Ac", (4, 9), "straight"),
        ("As Js 9s 6s 3s Kd 2c", (5, 14, 11, 9, 6, 3), "flush"),
        ("As Ad Ac Kh Ks 4d 2c", (6, 14, 13), "full house"),
        ("As Ad Ac Ah Ks 4d 2c", (7, 14, 13), "four of a kind"),
        ("9s 8s 7s 6s 5s Ad 2c", (8, 9), "straight flush"),
        ("As Ks Qs Js Ts 2d 2c", (9, 14), "royal flush"),
    )

    def test_every_category_has_exact_expected_rank(self) -> None:
        for codes, expected_rank, expected_name in self.CATEGORY_HANDS:
            with self.subTest(category=expected_name):
                rank, name = evaluate_seven_cards(cards(codes))
                self.assertEqual(rank, expected_rank)
                self.assertEqual(name, expected_name)

    def test_adjacent_categories_are_strictly_ordered(self) -> None:
        ranks = [
            evaluate_seven_cards(cards(codes))[0] for codes, _, _ in self.CATEGORY_HANDS
        ]
        for lower, higher in zip(ranks[:-1], ranks[1:], strict=True):
            self.assertLess(lower, higher)

    def test_wheel_is_below_six_high_straight(self) -> None:
        wheel, _ = evaluate_seven_cards(cards("As 2d 3c 4h 5s 9d Kc"))
        six_high, _ = evaluate_seven_cards(cards("2s 3d 4c 5h 6s 9d Kc"))
        self.assertEqual(wheel, (4, 5))
        self.assertEqual(six_high, (4, 6))
        self.assertLess(wheel, six_high)

    def test_full_house_uses_highest_of_two_triples(self) -> None:
        rank, _ = evaluate_seven_cards(cards("As Ad Ac Ks Kd Kh 2c"))
        self.assertEqual(rank, (6, 14, 13))

    def test_two_pair_and_flush_kickers_break_ties(self) -> None:
        two_pair_queen, _ = evaluate_seven_cards(cards("As Ad Ks Kd Qh 3c 2s"))
        two_pair_jack, _ = evaluate_seven_cards(cards("Ah Ac Kh Kc Js 3d 2c"))
        self.assertGreater(two_pair_queen, two_pair_jack)

        ace_jack_flush, _ = evaluate_seven_cards(cards("As Js 9s 6s 3s Kd 2c"))
        ace_ten_flush, _ = evaluate_seven_cards(cards("Ah Th 9h 6h 3h Kd 2c"))
        self.assertGreater(ace_jack_flush, ace_ten_flush)

    def test_best_five_are_selected_from_seven(self) -> None:
        rank, category = evaluate_seven_cards(cards("As Ks Qs Js Ts 2d 2c"))
        self.assertEqual(rank, (9, 14))
        self.assertEqual(category, "royal flush")

    def test_board_play_produces_exact_tie(self) -> None:
        board = "As Ks Qs Js Ts"
        first, first_category = evaluate_seven_cards(cards(f"{board} 2d 3c"))
        second, second_category = evaluate_seven_cards(cards(f"{board} 9d 9c"))
        self.assertEqual(first, second)
        self.assertEqual(first, (9, 14))
        self.assertEqual(first_category, "royal flush")
        self.assertEqual(second_category, "royal flush")

    def test_duplicate_or_wrong_count_evaluation_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "distinct"):
            evaluate_seven_cards(cards("As As Qs Js Ts 2d 3c"))
        with self.assertRaisesRegex(ValueError, "exactly 7"):
            evaluate_seven_cards(cards("As Ks Qs Js Ts 2d"))
        invalid = cards("As Ks Qs Js Ts 2d") + ["3c"]  # type: ignore[list-item]
        with self.assertRaisesRegex(TypeError, "only Card"):
            evaluate_seven_cards(invalid)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
