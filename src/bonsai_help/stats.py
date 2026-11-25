"""Exact interval statistics for reported rates (the Clopper-Pearson part of the `stats`
extract, PORTING-MAP §3.4; Fisher, Holm and McNemar follow in B7-B8).

No floating-point tail sums: each bound is bisected on exact integer binomial tails.
"""

from __future__ import annotations

import math
from fractions import Fraction
from math import comb

CONFIDENCE = Fraction(19, 20)
BISECTION_BITS = 64  # each bound is bracketed to 2**-64, then the bracket's outer end is kept


def clopper_pearson(
    count: int, n: int, confidence: float | Fraction = CONFIDENCE
) -> tuple[float, float]:
    """The exact two-sided Clopper-Pearson interval for the proportion count/n.

    The lower bound is the p at which P(X >= count) equals (1 - confidence) / 2, the upper
    the p at which P(X <= count) equals it, X ~ Binomial(n, p): the beta quantiles
    Beta((1 - c)/2; count, n - count + 1) and Beta((1 + c)/2; count + 1, n - count). The
    lower bound is exactly 0 when count is 0 and the upper exactly 1 when count is n. A
    float confidence is read through its decimal text, so 0.95 is exactly 19/20.
    """
    if type(count) is not int or type(n) is not int or n < 1 or not 0 <= count <= n:
        raise ValueError(f"expected integers 0 <= count <= n and n >= 1, not {count!r} of {n!r}")
    tail = (1 - _confidence(confidence)) / 2
    scale = 1 << BISECTION_BITS
    lower, upper = 0.0, 1.0
    if count:
        # P(X >= count) rises with p: below the bound it is under the tail.
        low, _ = _bisect(
            lambda m: (
                _tail(n, m, range(count, n + 1)) * tail.denominator < tail.numerator * scale**n
            )
        )
        lower = low / scale
    if count < n:
        # P(X <= count) falls with p: below the bound it is over the tail.
        _, high = _bisect(
            lambda m: _tail(n, m, range(count + 1)) * tail.denominator > tail.numerator * scale**n
        )
        upper = high / scale
    return lower, upper


def _confidence(value) -> Fraction:
    if isinstance(value, Fraction):
        exact = value
    elif type(value) in (int, float) and math.isfinite(value):
        exact = Fraction(str(value))
    else:
        raise ValueError(f"confidence must be a number strictly between 0 and 1, not {value!r}")
    if not 0 < exact < 1:
        raise ValueError(f"confidence must be strictly between 0 and 1, not {value!r}")
    return exact


def _tail(n: int, m: int, counts: range) -> int:
    """sum C(n, k) p**k (1 - p)**(n - k) over `counts`, times 2**(bits * n), for p = m / 2**bits."""
    rest = (1 << BISECTION_BITS) - m
    return sum(comb(n, k) * m**k * rest ** (n - k) for k in counts)


def _bisect(below) -> tuple[int, int]:
    """Bracket, in units of 2**-bits, the point in (0, 1) where `below` turns false."""
    low, high = 0, 1 << BISECTION_BITS
    while high - low > 1:
        middle = (low + high) // 2
        if below(middle):
            low = middle
        else:
            high = middle
    return low, high
