import math

import pytest

from book import Book, depth_svg, synthetic_book


def flat_book(bid_sizes, ask_sizes, mid=100.0, tick=1.0):
    bids = [(mid - tick * (i + 1), s) for i, s in enumerate(bid_sizes)]
    asks = [(mid + tick * (i + 1), s) for i, s in enumerate(ask_sizes)]
    return Book(0.0, bids, asks)


# ------------------------------------------------------------------ basics

def test_levels_are_sorted_on_construction():
    b = Book(0, [(98, 1), (99, 1)], [(102, 1), (101, 1)])
    assert b.bids[0][0] == 99
    assert b.asks[0][0] == 101


def test_crossed_book_rejected():
    with pytest.raises(ValueError, match="crossed"):
        Book(0, [(101, 1)], [(100, 1)])


def test_mid_and_spread():
    b = flat_book([1], [1])
    assert b.mid == 100.0
    assert b.spread == 2.0
    assert math.isclose(b.spread_bps, 200.0)


# --------------------------------------------------------------- imbalance

def test_balanced_book_has_zero_imbalance():
    assert flat_book([1, 1, 1], [1, 1, 1]).imbalance(3) == 0.0


def test_bid_heavy_is_positive():
    assert flat_book([3, 3], [1, 1]).imbalance(2) > 0


def test_ask_heavy_is_negative():
    assert flat_book([1, 1], [3, 3]).imbalance(2) < 0


def test_imbalance_bounded():
    assert flat_book([10], [0.0001]).imbalance(1) < 1.0
    assert flat_book([5], [5]).imbalance(1) == 0.0


def test_imbalance_depends_on_depth():
    # Bid-heavy at level 1, ask-heavy deeper.
    b = flat_book([10, 1, 1], [1, 10, 10])
    assert b.imbalance(1) > 0
    assert b.imbalance(3) < 0


# -------------------------------------------------------------- microprice

def test_microprice_sits_between_best_quotes():
    b = flat_book([3], [1])
    assert b.best_bid < b.microprice < b.best_ask


def test_microprice_leans_toward_the_thin_side():
    # Heavy bid, thin ask -> next trade likelier at the ask -> microprice above mid.
    assert flat_book([10], [1]).microprice > flat_book([10], [1]).mid


def test_microprice_equals_mid_when_balanced():
    b = flat_book([2], [2])
    assert math.isclose(b.microprice, b.mid)


# ------------------------------------------------------------------ depth

def test_depth_within_band_excludes_far_levels():
    b = flat_book([1, 1, 1], [1, 1, 1], mid=100.0, tick=1.0)
    bid, ask = b.depth_within(150)  # 1.5% band = 1.5 price units
    assert bid == 1 and ask == 1


def test_sweep_cost_positive_for_both_sides():
    b = synthetic_book(seed=3)
    assert b.sweep_cost_bps(10_000, "buy") > 0
    assert b.sweep_cost_bps(10_000, "sell") > 0


def test_sweep_cost_grows_with_size():
    b = synthetic_book(seed=3)
    assert b.sweep_cost_bps(500_000, "buy") > b.sweep_cost_bps(10_000, "buy")


def test_sweep_returns_none_when_book_too_thin():
    assert flat_book([0.001], [0.001]).sweep_cost_bps(1_000_000, "buy") is None


def test_slope_is_positive_on_both_sides():
    bid_sl, ask_sl = synthetic_book(seed=5).slope()
    assert bid_sl > 0 and ask_sl > 0


# ------------------------------------------------------------- synthetic

def test_synthetic_is_reproducible():
    assert synthetic_book(seed=1).bids == synthetic_book(seed=1).bids


def test_tilt_creates_imbalance():
    assert synthetic_book(tilt=0.5, seed=2).imbalance() > 0.2
    assert synthetic_book(tilt=-0.5, seed=2).imbalance() < -0.2


def test_svg_is_wellformed():
    svg = depth_svg(synthetic_book(seed=4))
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert svg.count("<path") == 2
