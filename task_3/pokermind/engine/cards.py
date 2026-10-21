"""Seeded deck handling and deterministic seven-card hand evaluation."""

import random
from collections import Counter
from itertools import combinations
from typing import Sequence

from task_3.pokermind.core.domain import Card, Suit


HandRank = tuple[int, ...]

CATEGORY_NAMES = (
    "high card",
    "pair",
    "two pair",
    "three of a kind",
    "straight",
    "flush",
    "full house",
    "four of a kind",
    "straight flush",
    "royal flush",
)


class Deck:
    """A standard 52-card deck shuffled by an isolated seeded RNG."""

    def __init__(self, seed: int) -> None:
        self._cards = [Card(rank, suit) for suit in Suit for rank in range(2, 15)]
        random.Random(seed).shuffle(self._cards)

    @property
    def cards(self) -> tuple[Card, ...]:
        """Return the undealt cards in their current deal order."""
        return tuple(self._cards)

    def deal(self, count: int) -> list[Card]:
        """Remove and return exactly ``count`` cards from the top of the deck.

        Raises:
            TypeError: If count is not an integer.
            ValueError: If count is negative or more cards are requested than remain.
        """
        if isinstance(count, bool) or not isinstance(count, int):
            raise TypeError("Deal count must be a non-negative integer.")
        if count < 0:
            raise ValueError("Deal count cannot be negative.")
        if count > len(self._cards):
            raise ValueError(
                f"Cannot deal {count} cards; only {len(self._cards)} remain in the deck."
            )

        dealt = self._cards[:count]
        del self._cards[:count]
        return dealt


def _straight_high(ranks: Sequence[int]) -> int | None:
    unique_ranks = set(ranks)
    if unique_ranks == {14, 2, 3, 4, 5}:
        return 5
    if len(unique_ranks) == 5 and max(unique_ranks) - min(unique_ranks) == 4:
        return max(unique_ranks)
    return None


def _evaluate_five_cards(cards: Sequence[Card]) -> HandRank:
    ranks = [card.rank for card in cards]
    rank_counts = Counter(ranks)
    counts_descending = sorted(
        rank_counts.items(), key=lambda item: (item[1], item[0]), reverse=True
    )
    is_flush = len({card.suit for card in cards}) == 1
    straight_high = _straight_high(ranks)

    if is_flush and straight_high == 14:
        return (9, straight_high)
    if is_flush and straight_high is not None:
        return (8, straight_high)

    if counts_descending[0][1] == 4:
        four_rank = counts_descending[0][0]
        kicker = max(rank for rank in ranks if rank != four_rank)
        return (7, four_rank, kicker)

    triples = sorted(
        (rank for rank, count in rank_counts.items() if count == 3), reverse=True
    )
    pairs = sorted(
        (rank for rank, count in rank_counts.items() if count == 2), reverse=True
    )
    if triples and pairs:
        return (6, triples[0], pairs[0])

    descending_ranks = tuple(sorted(ranks, reverse=True))
    if is_flush:
        return (5, *descending_ranks)
    if straight_high is not None:
        return (4, straight_high)
    if triples:
        kickers = sorted((rank for rank in ranks if rank != triples[0]), reverse=True)
        return (3, triples[0], *kickers)
    if len(pairs) == 2:
        kicker = next(rank for rank, count in rank_counts.items() if count == 1)
        return (2, pairs[0], pairs[1], kicker)
    if len(pairs) == 1:
        kickers = sorted((rank for rank in ranks if rank != pairs[0]), reverse=True)
        return (1, pairs[0], *kickers)
    return (0, *descending_ranks)


def evaluate_seven_cards(cards: Sequence[Card]) -> tuple[HandRank, str]:
    """Evaluate seven distinct cards and return comparison rank and category.

    Args:
        cards: Exactly seven distinct :class:`Card` values.

    Returns:
        A lexicographically comparable ranking tuple and human-readable category.

    Raises:
        TypeError: If an item is not a Card.
        ValueError: If there are not exactly seven distinct cards.
    """
    if len(cards) != 7:
        raise ValueError(
            f"Seven-card evaluation requires exactly 7 cards, got {len(cards)}."
        )
    if any(not isinstance(card, Card) for card in cards):
        raise TypeError("Seven-card evaluation accepts only Card values.")
    if len(set(cards)) != 7:
        raise ValueError("Seven-card evaluation requires 7 distinct cards.")

    best_rank = max(_evaluate_five_cards(combo) for combo in combinations(cards, 5))
    return best_rank, CATEGORY_NAMES[best_rank[0]]
