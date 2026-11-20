"""The Elo arithmetic of REQ-016, on plain numbers: start 1000, K 32, divisor 400.

Expected score = 1 / (1 + 10^((opponent - rating) / 400)); delta = 32 x (actual - expected). In
doubles the two pair averages are compared and each partner receives the side's delta. Nothing here
rounds: values are rounded only where they are shown.
"""

START = 1000.0
K = 32.0
DIVISOR = 400.0


def expected(own: float, opponent: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((opponent - own) / DIVISOR))


def average(ratings: list[float]) -> float:
    return sum(ratings) / len(ratings)


def deltas(side_a: list[float], side_b: list[float], a_won: bool) -> tuple[float, float, float, float]:
    """One rated match between two sides (one rating each for singles, two for doubles). Returns the
    delta of side a, the delta of side b, and the expected scores of a and b."""
    own_a, own_b = average(side_a), average(side_b)
    expected_a, expected_b = expected(own_a, own_b), expected(own_b, own_a)
    delta_a = K * ((1.0 if a_won else 0.0) - expected_a)
    delta_b = K * ((0.0 if a_won else 1.0) - expected_b)
    return delta_a, delta_b, expected_a, expected_b
