"""Evening signal check for the oversold-reversion day strategy.

Run every weekday evening AFTER 6:00 PM ET:   python scripts/signal_check.py

RECONCILED: this script now contains ZERO strategy logic of its own. It loads
the rules from config/default.yaml `live:` and calls quantlab.live_strategy --
the same module scripts/backtest_live_rules.py tests. The live rules and the
tested rules are literally the same object.

If it says TRADE, the plan for tomorrow is fixed and mechanical:
  ENTER : at entry_time ET (market order), instrument/size per config
  STOP  : stop_pct below entry (above, for a short), placed immediately
  EXIT  : exit_time ET (market order), or the stop, whichever comes first
  No re-entries. No discretion. One trade, then done.

After the trade, record the fill:  python scripts/log_trade.py ...
That log is what feeds evalsim (needs >= 15 real trading days).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

import pandas as pd
import yaml

sys.path.insert(0, ".")
from quantlab.live_strategy import LiveRules, latest_signal

LOG = "signals_log.csv"


def main() -> None:
    cfg = yaml.safe_load(open("config/default.yaml"))
    rules = LiveRules.from_config(cfg)

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

    s = latest_signal(d["close"], rules)
    print(f"As of close {last_date}:  RSI2={s['rsi2']:.1f}  "
          f"down_streak={s['down_streak']}  up_streak={s['up_streak']}  "
          f"shorts_enabled={rules.enable_shorts}")

    if s["sig"] == 1:
        print("\n*** SIGNAL: LONG the next session ***")
        print(f"  Long {rules.instrument} at {rules.entry_time} ET | "
              f"hard stop -{rules.stop_pct:.1%} | exit {rules.exit_time} ET")
    elif s["sig"] == -1:
        print("\n*** SIGNAL: SHORT the next session ***")
        print(f"  Short {rules.instrument} at {rules.entry_time} ET | "
              f"hard stop +{rules.stop_pct:.1%} | exit {rules.exit_time} ET")
    else:
        print("\nNO TRADE next session.")
        if not rules.enable_shorts:
            # Shadow visibility: would the short side have fired? Logged as info
            # only, so the short trigger accumulates a paper record pre-approval.
            shadow = latest_signal(d["close"], LiveRules(
                **{**rules.__dict__, "enable_shorts": True}))
            if shadow["short_sig"]:
                print("(note: SHORT trigger fired but shorts are disabled -- "
                      "untested side, logging for evidence only)")

    row = pd.DataFrame([{
        "signal_date": str(last_date), "close": float(d["close"].iloc[-1]),
        "rsi2": round(s["rsi2"], 2), "down3": s["down_streak"] >= rules.consec_down_days,
        "trade_next_day": s["sig"] == 1, "sig": s["sig"],
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
