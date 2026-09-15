#!/usr/bin/env python3
"""Orderbook imbalance metrics, and a depth chart that needs no plotting library.

The top-of-book spread tells you almost nothing on its own. What moves price
over the next few seconds is the shape of the book: how much size sits on each
side, how far you have to walk to fill, and whether the mid is actually where
trades will happen. These are the standard microstructure measures for that,
computed from L2 snapshots.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

Level = tuple[float, float]  # (price, size)


@dataclass
class Book:
    """One L2 snapshot. Bids descending by price, asks ascending."""

    ts: float
    bids: list[Level]
    asks: list[Level]

    def __post_init__(self) -> None:
        self.bids = sorted(self.bids, key=lambda l: -l[0])
        self.asks = sorted(self.asks, key=lambda l: l[0])
        if self.bids and self.asks and self.bids[0][0] >= self.asks[0][0]:
            raise ValueError(f"crossed book at ts={self.ts}: bid {self.bids[0][0]} >= ask {self.asks[0][0]}")

    # ------------------------------------------------------------ top of book
    @property
    def best_bid(self) -> float:
        return self.bids[0][0]

    @property
    def best_ask(self) -> float:
        return self.asks[0][0]

    @property
    def mid(self) -> float:
        return (self.best_bid + self.best_ask) / 2

    @property
    def spread(self) -> float:
        return self.best_ask - self.best_bid

    @property
    def spread_bps(self) -> float:
        return self.spread / self.mid * 10_000

    # ---------------------------------------------------------- imbalance
    def imbalance(self, depth: int = 5) -> float:
        """Order book imbalance in [-1, 1]. Positive means bid-heavy.

        The single most-used predictor of short-horizon price direction, and
        the one most often computed on one level when it should use several.
        """
        bid_size = sum(s for _, s in self.bids[:depth])
        ask_size = sum(s for _, s in self.asks[:depth])
        total = bid_size + ask_size
        return (bid_size - ask_size) / total if total else 0.0

    @property
    def microprice(self) -> float:
        """Size-weighted mid. Sits nearer the side with less size, which is
        where the next trade is more likely to print."""
        bid_p, bid_s = self.bids[0]
        ask_p, ask_s = self.asks[0]
        total = bid_s + ask_s
        return (bid_p * ask_s + ask_p * bid_s) / total if total else self.mid

    @property
    def microprice_tilt_bps(self) -> float:
        """How far the microprice sits from the mid, in basis points."""
        return (self.microprice - self.mid) / self.mid * 10_000

    def depth_within(self, bps: float) -> tuple[float, float]:
        """Size resting within `bps` of the mid, per side."""
        band = self.mid * bps / 10_000
        bid = sum(s for p, s in self.bids if p >= self.mid - band)
        ask = sum(s for p, s in self.asks if p <= self.mid + band)
        return bid, ask

    def sweep_cost_bps(self, notional: float, side: str) -> float | None:
        """Cost of taking `notional` immediately, in bps versus the mid.

        None when the visible book cannot fill the order, which is itself the
        answer worth knowing.
        """
        levels = self.asks if side == "buy" else self.bids
        remaining, qty, cost = notional, 0.0, 0.0
        for price, size in levels:
            take_notional = min(remaining, price * size)
            qty += take_notional / price
            cost += take_notional
            remaining -= take_notional
            if remaining <= 1e-9:
                break
        else:
            return None  # visible book cannot fill the order
        vwap = cost / qty
        signed = 1 if side == "buy" else -1
        return signed * (vwap - self.mid) / self.mid * 10_000

    def slope(self, depth: int = 10) -> tuple[float, float]:
        """Size accumulated per bp of distance from mid, per side.

        A steep book absorbs flow; a flat one gaps.
        """
        def side_slope(levels: list[Level], sign: int) -> float:
            total_size = distance = 0.0
            for price, size in levels[:depth]:
                total_size += size
                distance += abs(price - self.mid) / self.mid * 10_000 * size
            return total_size / (distance / total_size) if total_size and distance else 0.0

        return side_slope(self.bids, 1), side_slope(self.asks, -1)


def order_flow_imbalance(prev: Book, curr: Book, depth: int = 5) -> float:
    """Order-flow imbalance between two snapshots, in size units (Cont et al.).

    Almost all of the book's short-horizon information is in how it *changed*,
    not how it looks: a bid that grew and an ask that shrank both mean buying
    pressure. Positive means net buying.
    """
    ofi = 0.0
    n = min(depth, len(prev.bids), len(curr.bids), len(prev.asks), len(curr.asks))
    for i in range(n):
        pb, qb = curr.bids[i]
        pb0, qb0 = prev.bids[i]
        pa, qa = curr.asks[i]
        pa0, qa0 = prev.asks[i]
        if pb > pb0:
            ofi += qb
        elif pb == pb0:
            ofi += qb - qb0
        else:
            ofi -= qb0
        if pa < pa0:
            ofi -= qa
        elif pa == pa0:
            ofi -= qa - qa0
        else:
            ofi += qa0
    return ofi


def kyle_lambda(books: list[Book], depth: int = 5) -> float:
    """Price impact per unit of order flow, in bp per size.

    The OLS slope of mid-price change (bp) regressed on order-flow imbalance
    across consecutive snapshots: a direct analogue of Kyle's lambda, with OFI
    standing in for signed trade volume, which an L2 feed does not give you.
    A steep (large) lambda means the book is easily pushed.
    """
    if len(books) < 3:
        raise ValueError("need at least 3 snapshots to estimate impact")
    xs = [order_flow_imbalance(a, b, depth) for a, b in zip(books, books[1:])]
    ys = [(b.mid - a.mid) / a.mid * 10_000 for a, b in zip(books, books[1:])]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom


def load_jsonl(path: Path) -> list[Book]:
    """One JSON snapshot per line: {"ts":..., "bids":[[p,s],...], "asks":[...]}"""
    books: list[Book] = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                books.append(Book(raw["ts"],
                                  [tuple(l) for l in raw["bids"]],
                                  [tuple(l) for l in raw["asks"]]))
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                raise SystemExit(f"{path}:{lineno}: {exc}") from exc
    return books


def synthetic_book(mid: float = 50_000.0, levels: int = 20, tick: float = 1.0,
                   tilt: float = 0.0, seed: int | None = None, ts: float = 0.0) -> Book:
    """Build a plausible book. `tilt` in [-1, 1] biases size toward one side."""
    rng = random.Random(seed)
    bids, asks = [], []
    for i in range(levels):
        decay = math.exp(-i / 6)
        bids.append((mid - tick * (i + 1),
                     round(rng.uniform(0.5, 3.0) * decay * (1 + tilt), 4)))
        asks.append((mid + tick * (i + 1),
                     round(rng.uniform(0.5, 3.0) * decay * (1 - tilt), 4)))
    return Book(ts, bids, asks)


def depth_svg(book: Book, width: int = 720, height: int = 260, levels: int = 15) -> str:
    """Cumulative depth on both sides. The classic staircase."""
    bids = book.bids[:levels]
    asks = book.asks[:levels]
    if not bids or not asks:
        raise ValueError("need both sides to draw depth")

    cum_b, cum_a, running = [], [], 0.0
    for p, s in bids:
        running += s
        cum_b.append((p, running))
    running = 0.0
    for p, s in asks:
        running += s
        cum_a.append((p, running))

    lo, hi = cum_b[-1][0], cum_a[-1][0]
    max_size = max(cum_b[-1][1], cum_a[-1][1])
    pad_l, pad_r, pad_t, pad_b = 12, 12, 20, 30
    pw, ph = width - pad_l - pad_r, height - pad_t - pad_b

    def x(p: float) -> float:
        return pad_l + (p - lo) / (hi - lo) * pw

    def y(s: float) -> float:
        return pad_t + (1 - s / max_size) * ph

    def staircase(points, closing_x):
        d = [f"M {closing_x:.1f},{y(0):.1f}"]
        for p, s in points:
            d.append(f"L {x(p):.1f},{y(s):.1f}" if len(d) == 1 else f"L {x(p):.1f},{d[-1].split(',')[1]}")
            d.append(f"L {x(p):.1f},{y(s):.1f}")
        d.append(f"L {x(points[-1][0]):.1f},{y(0):.1f} Z")
        return " ".join(d)

    bid_path = " ".join(
        [f"M {x(book.mid):.1f},{y(0):.1f}"] +
        [f"L {x(p):.1f},{y(s):.1f}" for p, s in cum_b] +
        [f"L {x(cum_b[-1][0]):.1f},{y(0):.1f} Z"]
    )
    ask_path = " ".join(
        [f"M {x(book.mid):.1f},{y(0):.1f}"] +
        [f"L {x(p):.1f},{y(s):.1f}" for p, s in cum_a] +
        [f"L {x(cum_a[-1][0]):.1f},{y(0):.1f} Z"]
    )

    imb = book.imbalance()
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" font-family="ui-monospace, SFMono-Regular, Menlo, monospace">
  <rect width="{width}" height="{height}" fill="#0F1518"/>
  <path d="{bid_path}" fill="#3D6B5A" fill-opacity="0.55" stroke="#5A9B82" stroke-width="1.5"/>
  <path d="{ask_path}" fill="#7A3F38" fill-opacity="0.55" stroke="#B4675C" stroke-width="1.5"/>
  <line x1="{x(book.mid):.1f}" y1="{pad_t}" x2="{x(book.mid):.1f}" y2="{pad_t + ph}" stroke="#8A9490" stroke-width="1" stroke-dasharray="3 3"/>
  <text x="{pad_l}" y="{height - 10}" fill="#7C918F" font-size="10">{lo:,.0f}</text>
  <text x="{width - pad_r}" y="{height - 10}" fill="#7C918F" font-size="10" text-anchor="end">{hi:,.0f}</text>
  <text x="{x(book.mid):.1f}" y="{height - 10}" fill="#B8C4C2" font-size="10" text-anchor="middle">{book.mid:,.1f}</text>
  <text x="{pad_l}" y="14" fill="#B8C4C2" font-size="11">imbalance {imb:+.3f} &#183; spread {book.spread_bps:.2f}bp &#183; tilt {book.microprice_tilt_bps:+.2f}bp</text>
</svg>"""


def main() -> None:
    p = argparse.ArgumentParser(description="Orderbook imbalance metrics.")
    p.add_argument("jsonl", type=Path, nargs="?", help="L2 snapshots, one JSON per line")
    p.add_argument("--demo", action="store_true", help="use a synthetic bid-heavy book")
    p.add_argument("--svg", type=Path, default=None)
    args = p.parse_args()

    if args.demo or not args.jsonl:
        books = [synthetic_book(mid=50_000 + 20 * i * i, tilt=0.10 + 0.10 * i, seed=7, ts=float(i))
                 for i in range(3)]
    else:
        books = load_jsonl(args.jsonl)
        if not books:
            raise SystemExit("no snapshots found")

    book = books[-1]
    bid_d, ask_d = book.depth_within(10)
    bid_sl, ask_sl = book.slope()
    if len(books) >= 2:
        ofi = order_flow_imbalance(books[-2], books[-1])
    else:
        ofi = None
    lam = kyle_lambda(books) if len(books) >= 3 else None

    print(f"\n  mid                 {book.mid:>12,.2f}")
    print(f"  spread              {book.spread_bps:>12.3f} bp")
    print(f"  microprice          {book.microprice:>12,.2f}  ({book.microprice_tilt_bps:+.3f} bp from mid)")
    print()
    for d in (1, 5, 10, 20):
        print(f"  imbalance @{d:<3}       {book.imbalance(d):>+12.4f}")
    print()
    print(f"  depth within 10bp   {bid_d:>12,.3f} bid / {ask_d:,.3f} ask")
    print(f"  slope               {bid_sl:>12,.3f} bid / {ask_sl:,.3f} ask  (size per bp)")
    if ofi is not None:
        print(f"  OFI (last step)     {ofi:>+12,.3f}          (net size, + buying)")
    if lam is not None:
        print(f"  kyle lambda         {lam:>+12.5f}          (bp per size)")
    print()
    for notional in (10_000, 100_000, 1_000_000):
        buy = book.sweep_cost_bps(notional, "buy")
        sell = book.sweep_cost_bps(notional, "sell")
        fmt = lambda v: f"{v:>8.2f}bp" if v is not None else "  no fill"
        print(f"  sweep {notional:>9,.0f}   buy {fmt(buy)}   sell {fmt(sell)}")

    if args.svg:
        args.svg.write_text(depth_svg(book), encoding="utf-8")
        print(f"\n  depth chart -> {args.svg}")
    print()


if __name__ == "__main__":
    main()
