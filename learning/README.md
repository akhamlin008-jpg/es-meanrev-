# learning/ — how this system gets smarter as it ages

You asked for "machine learning." Honest answer first: with the data volume
this system produces (a daily-frequency signal firing ~1-3 times/week, one
trade per signal), fitting an ML model now would be textbook overfitting —
hundreds of parameters chasing dozens of observations. Any backtest of it
would look great and mean nothing. That is not a limitation of this repo;
it is arithmetic.

What IS real: a system that **accumulates evidence and recalibrates itself
against reality on a schedule**. That compounds. The ladder, in order:

## Stage 1 — accumulate (running now)
Every nightly run and every logged trade adds to four growing datasets:
- `signals_log.csv` — every signal decision, hit or miss
- `trades_log.csv` / `daily_pnl.csv` — real fills, real P&L (log_trade.py)
- `data/cache/es_1min.parquet` — free 1-min forward data (update_cache.py)
- `learning/calibration.json` — outputs of Stage 2, versioned over time

Data is the only input that makes anything downstream possible. Zero config.

## Stage 2 — recalibrate against reality (scripts/recalibrate.py)
Run weekly. It compares what the models ASSUMED to what actually HAPPENED:
- **Cost calibration**: modeled slippage (config) vs realized slippage
  (broker P&L overrides vs computed P&L in trades_log). If reality is worse,
  the config number should rise — costs are the one thing you can measure
  precisely from day one.
- **Signal health**: rolling win rate and mean P&L of logged trades with a
  Wilson confidence interval, vs the backtest's expectation. Prints a
  degradation flag when the live record falls below the backtest's 5th
  percentile — the earliest honest "the edge may be gone" alarm possible.
- **Shadow-side ledger**: what the disabled short side WOULD have done on
  each signal day (priced from the cache), building its case file without
  risking a dollar.

## Stage 3 — walk-forward parameter review (quarterly, manual trigger)
Re-run validate_spy.py and backtest_live_rules.py on data that has arrived
SINCE the last review. Parameters (RSI threshold, stop %) may be adjusted
only on out-of-sample evidence, and every change is a config commit with the
evidence linked in the message. No silent drift.

## Stage 4 — actual ML (gated, not scheduled)
Justified only when trades_log.csv holds **200+ real trades** — realistically
1-2 years out. The first legitimate model is small: logistic regression of
trade outcome on a handful of pre-trade features (VIX level, gap size,
signal strength, day of week), walk-forward validated, used to SKIP the worst
signals rather than to invent new ones. Anything fancier before that data
exists is decoration.

The gate is written down here so future-you doesn't rationalize skipping it.
