"""Exact Clopper-Pearson intervals: reference values, edges and impossible counts."""

from __future__ import annotations

from fractions import Fraction
from math import comb

import pytest

from bonsai_help.stats import clopper_pearson


def tail_at_least(count: int, n: int, p: float) -> float:
    return sum(comb(n, k) * p**k * (1 - p) ** (n - k) for k in range(count, n + 1))


def tail_at_most(count: int, n: int, p: float) -> float:
    return sum(comb(n, k) * p**k * (1 - p) ** (n - k) for k in range(count + 1))


def test_reference_values():
    low, high = clopper_pearson(70, 70)
    assert round(low, 4) == 0.9487 and high == 1.0
    assert low == pytest.approx(0.025 ** (1 / 70), abs=1e-12)
    low, high = clopper_pearson(56, 70)
    assert (round(low, 4), round(high, 4)) == (0.6873, 0.8861)
    low, high = clopper_pearson(15, 20)
    assert (round(low, 4), round(high, 4)) == (0.5090, 0.9134)
    low, high = clopper_pearson(0, 20)
    assert low == 0.0
    assert high == pytest.approx(1 - 0.025 ** (1 / 20), abs=1e-12)


def test_bounds_are_the_exact_binomial_tail_points():
    # The definition, not a copy of the method: at each bound the one-sided tail is 2.5%.
    low, high = clopper_pearson(56, 70)
    assert tail_at_least(56, 70, low) == pytest.approx(0.025, abs=1e-12)
    assert tail_at_most(56, 70, high) == pytest.approx(0.025, abs=1e-12)
    low, high = clopper_pearson(3, 50, confidence=0.9)
    assert tail_at_least(3, 50, low) == pytest.approx(0.05, abs=1e-12)
    assert tail_at_most(3, 50, high) == pytest.approx(0.05, abs=1e-12)


def test_edges_and_symmetry():
    low, high = clopper_pearson(1, 1)
    assert low == pytest.approx(0.025, abs=1e-15) and high == 1.0
    low, high = clopper_pearson(0, 1)
    assert low == 0.0 and high == pytest.approx(0.975, abs=1e-15)
    low, high = clopper_pearson(0, 70)
    assert low == 0.0 and high == pytest.approx(1 - 0.025 ** (1 / 70), abs=1e-12)
    low, high = clopper_pearson(10, 20)
    assert low == pytest.approx(1 - high, abs=1e-12)
    assert 0.0 < low < 0.5 < high < 1.0
    # A wider confidence gives a wider interval around the same count.
    narrow, wide = clopper_pearson(30, 60, confidence=0.9), clopper_pearson(30, 60, 0.99)
    assert wide[0] < narrow[0] and narrow[1] < wide[1]


def test_exact_confidence_values_are_accepted():
    assert clopper_pearson(56, 70, Fraction(19, 20)) == clopper_pearson(56, 70)


@pytest.mark.parametrize(
    ("count", "n"),
    [(-1, 20), (21, 20), (0, 0), (1, 0), (True, 20), (1, True), (1.0, 20), (1, 20.0), ("1", 2)],
)
def test_impossible_counts_are_refused(count, n):
    with pytest.raises(ValueError):
        clopper_pearson(count, n)


@pytest.mark.parametrize("confidence", [0, 1, 1.5, -0.5, True, "0.95", float("nan"), None])
def test_impossible_confidence_is_refused(confidence):
    with pytest.raises(ValueError):
        clopper_pearson(5, 10, confidence)
