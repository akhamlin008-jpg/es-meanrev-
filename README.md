# es-meanrev — ES futures mean-reversion research framework (Tradeify-aware)

Research framework for developing and validating a mean-reversion system on ES/MES
futures under Tradeify prop-firm rules. This is Phase 1: machinery, not results.
No performance claims are made until backtests run on real data and survive
out-of-sample validation.

## Quick start

    pip install -r requirements.txt
    python scripts/signal_check.py          # nightly: TRADE / NO-TRADE (live rules)
    python scripts/backtest_live_rules.py   # backtest of THOSE EXACT rules
    python scripts/validate_spy.py          # long-history validation, both sides
    python scripts/log_trade.py --help      # record real fills -> daily_pnl.csv
    python scripts/run_evalsim.py           # P(pass) etc. once >= 15 traded days
    python scripts/recalibrate.py           # weekly: model vs reality

## Reconciliation (the design rule that governs this repo)

quantlab/live_strategy.py is the SINGLE SOURCE OF TRUTH for the live rules,
parameterized by the `live:` block in config/default.yaml. Three consumers:
scripts/signal_check.py (nightly signal), scripts/backtest_live_rules.py
(backtest of the live rules on 1-min data), scripts/validate_spy.py
(long-history validation). Change a rule in config and all three change
together. Never add strategy logic to a script; add it to live_strategy.py.

Shorts (RSI2 > 85 OR 3 up closes) are implemented but `enable_shorts: false`
until they pass validate_spy.py drift-adjusted AND the live-rules backtest.
Index reversion is not symmetric; the short side must earn its own evidence.

Sizing: `execution.max_contracts` is per-instrument (ES: 4, MES: 40), and the
engine resolves the cap from what you actually trade, so running MES no
longer inherits the 4-contract mini cap.

## Repo layout

    config/default.yaml     all parameters; nothing is hardcoded in modules
    quantlab/contracts.py   tick specs (ES, MES)
    quantlab/costs.py       commission + slippage model, cost-adjusted breakeven WR
    quantlab/data.py        loader (CSV/parquet, tz handling), audit, session labels
    quantlab/indicators.py  EMA/RMA/RSI/CCI/zscore/ATR (Pine-compatible where relevant)
    quantlab/sizing.py      frac_pct + dd_frac (UNCONFIRMED — see below), sizing log
    quantlab/account.py     Tradeify rule simulator (trailing DD, DLL, consistency, HFT rule)
    quantlab/strategies.py  zscore_mr baseline + faithful Pine indicator port
    quantlab/engine.py      event-driven bar engine, conservative fill discipline
    quantlab/report.py      metrics + per-session breakdown
    quantlab/evalsim.py     Monte Carlo P(pass) / $-per-funded-account
    quantlab/cache.py       free Yahoo ES=F 1-min rolling cache (run >= every ~5 days)
    scripts/                runners
    calendars/events.csv    FOMC/CPI dates — fill from official calendars, do not guess

## Decisions on record

- Account pick: Select 50K (provisional) — funded-stage payout convexity
  (no consistency rule / no DLL on the Flex path) beats Growth's 35% funded
  consistency rule. To be confirmed/overturned by evalsim on real trade data.
- Eval geometry: 0.5R target per spec. Breakeven win rate is ~66.7% before costs,
  ~72% after realistic ES costs at a 12-tick stop. The report prints the exact
  cost-adjusted bar next to achieved win rate; if it fails, the geometry changes.
- frac_2pct on nominal $50k equity vs a $2,000 trailing DD degenerates to
  always-max-size after guardrail clamping. `equity_basis: dd_allowance` is the
  testable alternative. The eval simulator arbitrates; nobody assumes.

## UNCONFIRMED: dd_frac_40pct

The post-eval sizing scheme's definition comes from a heatmap label with no
formula. Three candidate variants are implemented (floor_scaled,
allowance_fraction, fixed_f) and the module REFUSES TO RUN until
`sizing.dd_frac.variant` is set explicitly after confirming against the source.
Do not guess — the variants differ by ~an order of magnitude in size.

## Verify before spending money (none of these are baked-in facts)

- Tradeify Select/Growth 50K: target, trailing DD amount, contract caps, fees,
  consistency percentages, funded-stage payout policies — check tradeify.co.
- Tradovate commission per round turn — check your fee schedule.
- Bot policy: personal, solely-owned bots allowed, no HFT; confirm your
  interpretation with Tradeify support before deploying automation.

## Known limitations (stated, not hidden)

- Bar-based fills: intrabar path unknowable; stop-first + limit-trade-through
  assumptions bias results pessimistic (the correct direction of error).
- evalsim intraday-excursion proxy is crude; will be replaced by true intraday
  equity paths from the engine.
- Free data (GitHub dump + Yahoo cache) has unverified provenance; audit runs
  on every load and every cache update. ~60 days of history is one regime of
  one quarter — parameters that look good on it alone are presumptively overfit.
- Walk-forward, permutation Monte Carlo, and parameter-sensitivity modules are
  the next deliverable, gated on the data audit passing.
