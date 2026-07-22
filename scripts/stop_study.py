"""Stop study for the oversold-reversion day strategy (long at open on signal
days, exit at close), simulated across full SPY history using daily OHLC.

For each stop level S: if the day's LOW breaches open*(1-S), the trade exits at
the stop price (approximation: fill AT the stop; real fills are slightly worse).
Otherwise it exits at the close. Outputs, per stop level and era:
  mean return, t-stat, win rate, worst day, % of days stopped, and the
  "whipsaw cost" (mean of close-vs-stop on stopped days that later recovered).

Conservatism note: using the daily low assumes the stop is hit if the low ever
touched it -- correct. But we cannot know intraday ORDER (a day whose low came
after a big rally still counts as stopped only if low breached). This method is
standard and slightly conservative for tight stops.

Run:  python scripts/stop_study.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

STOPS = [0.005, 0.0075, 0.01, 0.015, 0.02, 0.03, None]   # None = no stop


def rsi2(close: pd.Series) -> pd.Series:
    ch = close.diff()
    up = ch.clip(lower=0).ewm(alpha=1 / 2, adjust=False).mean()
    dn = (-ch).clip(lower=0).ewm(alpha=1 / 2, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def line(label: str, r: pd.Series, stopped: pd.Series) -> str:
    r = r.dropna()
    if len(r) < 10:
        return f"{label:16s} (too few)"
    t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))
    return (f"{label:16s} n={len(r):4d}  mean={r.mean()*100:+.3f}%  t={t:+5.2f}  "
            f"win={(r > 0).mean():.0%}  worst={r.min()*100:+.2f}%  "
            f"stopped={stopped.mean():.0%}")


def main() -> None:
    import yfinance as yf
    d = yf.download("SPY", period="max", interval="1d", auto_adjust=False, progress=False)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = [c[0].lower() for c in d.columns]
    else:
        d.columns = [c.lower() for c in d.columns]
    d = d[["open", "high", "low", "close"]].dropna().copy()

    d["r"] = rsi2(d["close"])
    down = d["close"].diff().lt(0)
    d["down3"] = (down & down.shift(1) & down.shift(2)).fillna(False)
    d["sig_prev"] = ((d["r"] < 15) | d["down3"]).shift(1).fillna(False).astype(bool)

    s = d[d["sig_prev"]].copy()
    print(f"Signal days: {len(s)}  span: {s.index[0].date()} -> {s.index[-1].date()}\n")

    for era_label, a, b in (("ALL 1993-2026", "1993", "2027"),
                            ("RECENT 2020-2026", "2020", "2027")):
        e = s[(s.index >= a) & (s.index < b)]
        print(f"=== {era_label} ===")
        for stop in STOPS:
            if stop is None:
                r = e["close"] / e["open"] - 1
                stopped = pd.Series(False, index=e.index)
                lbl = "no stop"
            else:
                stop_px = e["open"] * (1 - stop)
                hit = e["low"] <= stop_px
                r = np.where(hit, -stop, e["close"] / e["open"] - 1)
                r = pd.Series(r, index=e.index)
                stopped = hit
                lbl = f"stop {stop*100:.2f}%"
            print(line(lbl, r, stopped))
        # whipsaw diagnosis at the 1% stop: of stopped days, how many closed
        # ABOVE the stop price (i.e., the stop turned a recovery into a loss)?
        stop_px = e["open"] * 0.99
        hit = e["low"] <= stop_px
        rec = (e["close"] > stop_px) & hit
        if hit.sum() > 0:
            print(f"  [1% stop diagnosis: {int(hit.sum())} stopped, "
                  f"{int(rec.sum())} of those recovered above the stop by the close "
                  f"-> whipsaw rate {rec.sum()/hit.sum():.0%}]")
        print()


if __name__ == "__main__":
    main()
