"""Evening signal check for the oversold-reversion day strategy.

Run every weekday evening AFTER 6:00 PM ET:   python scripts/signal_check.py

It downloads ES=F daily closes, computes the signal (2-period RSI < 15 OR
three consecutive down days), prints TRADE or NO TRADE for the next session,
and appends the decision to signals_log.csv -- your paper-trade record.

If it says TRADE, the plan for tomorrow is fixed and mechanical:
  ENTER : long 1 MES at 10:00 AM ET (market order)
  STOP  : 2.0% below your entry price (hard stop, placed immediately)
  EXIT  : 3:55 PM ET (market order), or the stop, whichever comes first
  No re-entries. No discretion. One trade, then done.
"""
from __future__ import annotations

import os
from datetime import datetime

import numpy as np
import pandas as pd

LOG = "signals_log.csv"


def rsi2(close: pd.Series) -> pd.Series:
    ch = close.diff()
    up = ch.clip(lower=0).ewm(alpha=1 / 2, adjust=False).mean()
    dn = (-ch).clip(lower=0).ewm(alpha=1 / 2, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def main() -> None:
    import yfinance as yf
    d = yf.download("ES=F", period="6mo", interval="1d",
                    auto_adjust=False, progress=False)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = [c[0].lower() for c in d.columns]
    else:
        d.columns = [c.lower() for c in d.columns]
    d = d[["close"]].dropna()
    last_date = d.index[-1].date()
    age_days = (datetime.now().date() - last_date).days
    if age_days > 3:
        print(f"WARNING: latest daily bar is {last_date} ({age_days} days old). "
              f"Data may be stale -- do not trust this signal.")

    r = rsi2(d["close"])
    down = d["close"].diff().lt(0)
    down3 = bool(down.iloc[-1] and down.iloc[-2] and down.iloc[-3])
    rsi_now = float(r.iloc[-1])
    signal = (rsi_now < 15) or down3

    print(f"As of close {last_date}:  RSI2={rsi_now:.1f}  three-down-days={down3}")
    if signal:
        print("\n*** SIGNAL: TRADE THE NEXT SESSION ***")
        print("  Long 1 MES at 10:00 AM ET | hard stop -2.0% | exit 3:55 PM ET")
    else:
        print("\nNO TRADE next session.")

    row = pd.DataFrame([{
        "signal_date": str(last_date), "close": float(d['close'].iloc[-1]),
        "rsi2": round(rsi_now, 2), "down3": down3, "trade_next_day": signal,
        "logged_at": datetime.now().isoformat(timespec="seconds"),
    }])
    if os.path.exists(LOG):
        old = pd.read_csv(LOG)
        if str(last_date) in set(old["signal_date"].astype(str)):
            print(f"(already logged for {last_date}; log unchanged)")
            return
        row = pd.concat([old, row])
    row.to_csv(LOG, index=False)
    print(f"(logged to {LOG})")


if __name__ == "__main__":
    main()
