"""Long-history validation of the oversold-reversion tradable edge, on SPY.

Signal (from DAILY CLOSES): 2-period RSI < 15, OR three consecutive down days.
Tradable expression: NEXT day's open -> close return (long only).
SPY proxies the ES RTH session; decades of free data give the statistical
power that 13 months of futures data cannot.

Run:  python scripts/validate_spy.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def rsi2(close: pd.Series) -> pd.Series:
    ch = close.diff()
    up = ch.clip(lower=0).ewm(alpha=1 / 2, adjust=False).mean()
    dn = (-ch).clip(lower=0).ewm(alpha=1 / 2, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def report(label: str, x: pd.Series) -> str:
    x = x.dropna()
    if len(x) < 10:
        return f"{label:34s} n={len(x):4d} (too few)"
    t = x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
    return (f"{label:34s} n={len(x):4d}  mean={x.mean()*100:+.3f}%  t={t:+5.2f}  "
            f"win={(x > 0).mean():.0%}  worst={x.min()*100:+.2f}%")


def main() -> None:
    import yfinance as yf
    d = yf.download("SPY", period="max", interval="1d", auto_adjust=False, progress=False)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = [c[0].lower() for c in d.columns]
    else:
        d.columns = [c.lower() for c in d.columns]
    d = d[["open", "close"]].dropna().copy()
    print(f"SPY daily bars: {len(d)}  span: {d.index[0].date()} -> {d.index[-1].date()}\n")

    d["r"] = rsi2(d["close"])
    down = d["close"].diff().lt(0)
    d["down3"] = (down & down.shift(1) & down.shift(2)).fillna(False)
    d["sig"] = (d["r"] < 15) | d["down3"]
    d["sig_prev"] = d["sig"].shift(1).fillna(False)
    d["oc"] = d["close"] / d["open"] - 1          # same-day open->close (tradable)

    sig_days = d[d["sig_prev"]]
    base = d[~d["sig_prev"]]
    print(report("ALL HISTORY  signal-day open->close", sig_days["oc"]))
    print(report("ALL HISTORY  non-signal control", base["oc"]))
    print()

    print("By era (does the effect persist, or has it decayed?):")
    for a, b in (("1994", "2004"), ("2004", "2014"), ("2014", "2020"),
                 ("2020", "2023"), ("2023", "2027")):
        m = (d.index >= a) & (d.index < b) & d["sig_prev"]
        mb = (d.index >= a) & (d.index < b) & ~d["sig_prev"]
        print(report(f"  {a}-{b} signal", d.loc[m, "oc"]))
        print(report(f"  {a}-{b} control", d.loc[mb, "oc"]))
    print()

    x = sig_days["oc"].dropna() * 100
    print("Signal-day distribution (%): "
          f"p1={x.quantile(.01):+.2f} p5={x.quantile(.05):+.2f} p25={x.quantile(.25):+.2f} "
          f"med={x.median():+.2f} p75={x.quantile(.75):+.2f} p99={x.quantile(.99):+.2f}")
    print(f"Days below -2%: {(x < -2).sum()} of {len(x)}  |  below -4%: {(x < -4).sum()}")


if __name__ == "__main__":
    main()
