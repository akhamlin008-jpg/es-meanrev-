"""Long-history validation of the oversold-reversion tradable edge, on SPY.

RECONCILED: signals come from quantlab.live_strategy (the same module the
nightly signal and the live-rules backtest use), with thresholds read from
config/default.yaml. Change the config and this validation tests the change.

LONG side  (live):   RSI2 < rsi_long_below OR consec_down_days down closes
SHORT side (gated):  RSI2 > rsi_short_above OR consec_up_days up closes
Tradable expression: NEXT day's open -> close return, per side.

The SHORT side is reported drift-adjusted (short return minus the negated
unconditional daily open->close mean) because index upward drift is a headwind
every short day pays. A short trigger can look fine raw and still be worse
than doing nothing. Do NOT enable shorts unless the drift-adjusted line is
positive with a respectable t-stat across eras -- not just overall.

SPY proxies the ES RTH session; decades of free data give statistical power
that months of futures data cannot. Costs are NOT modeled here (this is a
signal test); the live-rules backtest models costs.

Run:  python scripts/validate_spy.py
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, ".")
from quantlab.live_strategy import LiveRules, daily_signal


def report(label: str, x: pd.Series) -> str:
    x = x.dropna()
    if len(x) < 10:
        return f"{label:40s} n={len(x):4d} (too few)"
    t = x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
    return (f"{label:40s} n={len(x):4d}  mean={x.mean()*100:+.3f}%  t={t:+5.2f}  "
            f"win={(x > 0).mean():.0%}  worst={x.min()*100:+.2f}%")


def main() -> None:
    cfg = yaml.safe_load(open("config/default.yaml"))
    rules = LiveRules(**{**LiveRules.from_config(cfg).__dict__, "enable_shorts": True})

    import yfinance as yf
    d = yf.download("SPY", period="max", interval="1d", auto_adjust=False, progress=False)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = [c[0].lower() for c in d.columns]
    else:
        d.columns = [c.lower() for c in d.columns]
    d = d[["open", "close"]].dropna().copy()
    print(f"SPY daily bars: {len(d)}  span: {d.index[0].date()} -> {d.index[-1].date()}\n")

    sig = daily_signal(d["close"], rules)
    d["long_prev"] = sig["long_sig"].shift(1).fillna(False).astype(bool)
    d["short_prev"] = sig["short_sig"].shift(1).fillna(False).astype(bool)
    d["oc"] = d["close"] / d["open"] - 1              # same-day open->close (tradable)
    drift = d["oc"].mean()
    print(f"Unconditional daily open->close drift: {drift*100:+.4f}%/day "
          f"(the headwind every short pays)\n")

    print("== LONG side (the live rules) ==")
    print(report("ALL HISTORY  long signal-day o->c", d.loc[d.long_prev, "oc"]))
    print(report("ALL HISTORY  control (no signal)", d.loc[~d.long_prev & ~d.short_prev, "oc"]))
    print()

    print("== SHORT side (gated -- must earn its way in) ==")
    sh_raw = -d.loc[d.short_prev, "oc"]               # P&L sign of a short
    sh_adj = -(d.loc[d.short_prev, "oc"] - drift)     # drift-adjusted
    print(report("ALL HISTORY  short RAW  (-o->c)", sh_raw))
    print(report("ALL HISTORY  short DRIFT-ADJ", sh_adj))
    print()

    print("By era (does either side persist, or decay?):")
    for a, b in (("1994", "2004"), ("2004", "2014"), ("2014", "2020"),
                 ("2020", "2023"), ("2023", "2027")):
        era = (d.index >= a) & (d.index < b)
        print(report(f"  {a}-{b} LONG", d.loc[era & d.long_prev, "oc"]))
        print(report(f"  {a}-{b} SHORT drift-adj", -(d.loc[era & d.short_prev, "oc"] - drift)))
    print()

    x = d.loc[d.long_prev, "oc"].dropna() * 100
    print("Long signal-day distribution (%): "
          f"p1={x.quantile(.01):+.2f} p5={x.quantile(.05):+.2f} p25={x.quantile(.25):+.2f} "
          f"med={x.median():+.2f} p75={x.quantile(.75):+.2f} p99={x.quantile(.99):+.2f}")
    print(f"Days below -2%: {(x < -2).sum()} of {len(x)}  |  below -4%: {(x < -4).sum()}")
    print("\nDecision rule: flip live.enable_shorts to true ONLY if the short "
          "drift-adjusted line is positive with |t| >= 2 overall AND does not "
          "flip sign era-to-era. Anything less is noise wearing a costume.")


if __name__ == "__main__":
    main()
