# orderbook

Microstructure metrics from L2 snapshots. The top-of-book spread tells you
almost nothing on its own; what moves price over the next few seconds is the
shape of the book.

```
$ python3 book.py --demo --svg depth.svg

  mid                    50,000.00
  spread                     0.400 bp
  microprice             50,000.51  (+0.102 bp from mid)

  imbalance @1              +0.5123
  imbalance @5              +0.4194
  imbalance @10             +0.3617

  depth within 10bp         12.231 bid / 5.405 ask
  slope                     12.146 bid / 4.631 ask  (size per bp)

  sweep    10,000   buy     0.20bp   sell     0.20bp
  sweep   100,000   buy     0.49bp   sell     0.22bp
  sweep 1,000,000   buy   no fill   sell   no fill
```

## What each measure is for

| measure | what it captures |
|---|---|
| imbalance | resting size skew; the most-used short-horizon direction predictor |
| microprice | size-weighted mid, nearer the thin side where the next trade prints |
| depth within N bp | how much size actually sits close enough to matter |
| sweep cost | what taking liquidity costs right now, in bps versus mid |
| slope | size per bp of distance; a steep book absorbs flow, a flat one gaps |

Imbalance takes a depth parameter, and it matters: the demo book is bid-heavy
at level 1 (+0.51) and less so across ten levels (+0.36). Computing it on one
level and calling it "the imbalance" is the usual mistake.

"No fill" from `sweep_cost_bps` is not an error. It is the answer: the visible
book cannot absorb that order.

## Input

JSONL, one snapshot per line:
```json
{"ts": 1721822400.0, "bids": [[49999, 1.2], [49998, 0.8]], "asks": [[50001, 0.9]]}
```

Crossed books are rejected at construction rather than silently producing
negative spreads.

Stdlib only. Tests: `python3 -m pytest test_book.py` (19 tests)
