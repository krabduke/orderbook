# orderbook

Microstructure metrics from L2 snapshots. The top-of-book spread tells you
almost nothing on its own; what moves price over the next few seconds is the
shape of the book.

```
$ python3 book.py --demo --svg depth.svg

  mid                    50,080.00
  spread                     0.399 bp
  microprice             50,080.47  (+0.094 bp from mid)

  imbalance @1              +0.4699
  imbalance @5              +0.3723
  imbalance @10             +0.3122
  imbalance @20             +0.3385

  depth within 10bp         11.778 bid / 5.821 ask
  slope                     11.715 bid / 4.995 ask  (size per bp)

  OFI (last step)          +10.145          (net size, + buying)
  kyle lambda           +103.43081          (bp per size)

  sweep    10,000   buy     0.20bp   sell     0.20bp
  sweep   100,000   buy     0.46bp   sell     0.23bp
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
| OFI | how the book *changed* between snapshots; almost all short-horizon signal is here, not in the static shape |
| kyle lambda | price impact per unit of order flow, in bp per size; a large lambda means the book is easily pushed |

Imbalance takes a depth parameter, and it matters: the demo book is bid-heavy
at level 1 (+0.51) and less so across ten levels (+0.36). Computing it on one
level and calling it "the imbalance" is the usual mistake.

"No fill" from `sweep_cost_bps` is not an error. It is the answer: the visible
book cannot absorb that order.

`order_flow_imbalance` and `kyle_lambda` need more than one snapshot: pass a
JSONL file with several lines. Kyle's lambda is the OLS slope of mid-price
change (bp) on OFI, because an L2 feed gives you no signed trade volume to use
instead. It is a proxy, and labelled as one.

## Input

JSONL, one snapshot per line:
```json
{"ts": 1721822400.0, "bids": [[49999, 1.2], [49998, 0.8]], "asks": [[50001, 0.9]]}
```

Crossed books are rejected at construction rather than silently producing
negative spreads.

Stdlib only. Tests: `python3 -m pytest test_book.py` (28 tests)
