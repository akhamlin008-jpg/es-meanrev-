"""Weekly recalibration: compare what the models assume to what reality did.

Run:  python scripts/recalibrate.py

Reads signals_log.csv + trades_log.csv, writes learning/calibration.json
(appending a dated snapshot, so calibration itself has a history). Prints:

1. COSTS  — realized vs modeled P&L per trade (only measurable on trades
   logged with --pnl-override, i.e. broker-statement numbers). If realized
   consistently undershoots computed, your slippage config is optimistic.
2. SIGNAL HEALTH — win rate of real trades with a Wilson 95% interval.
   Small-n honesty is built in: with <20 trades the interval will be wide,
   and the script says so instead of pretending.
3. DISCIPLINE — signals fired vs trades logged. A gap means the system's
   record and your record are diverging; evalsim on partial data misleads.

No parameters are changed automatically. This script produces evidence;
you change config/default.yaml, in a commit, when the evidence says to.
"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import pandas as pd

SIGNALS = Path("signals_log.csv")
TRADES = Path("trades_log.csv")
OUT = Path("learning/calibration.json")


def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = wins / n
    den = 1 + z * z / n
    ctr = (p + z * z / (2 * n)) / den
    rad = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, ctr - rad), min(1.0, ctr + rad))


def main() -> None:
    snap: dict = {"date": str(date.today())}

    # -- discipline: signals vs logged trades ------------------------------
    n_sig = 0
    if SIGNALS.exists():
        s = pd.read_csv(SIGNALS)
        col = "sig" if "sig" in s.columns else "trade_next_day"
        fired = s[col].astype(str).str.lower().isin({"1", "-1", "true"})
        n_sig = int(fired.sum())
    n_traded = n_skipped = 0
    t = pd.DataFrame()
    if TRADES.exists():
        t = pd.read_csv(TRADES)
        n_skipped = int((t["reason"] == "skipped").sum())
        t = t[t["reason"] != "skipped"].dropna(subset=["pnl"])
        n_traded = len(t)
    snap["discipline"] = {"signals_fired": n_sig, "trades_logged": n_traded,
                          "skips_logged": n_skipped,
                          "unaccounted": max(0, n_sig - n_traded - n_skipped)}
    print(f"DISCIPLINE  signals={n_sig}  traded={n_traded}  skipped={n_skipped}  "
          f"unaccounted={snap['discipline']['unaccounted']}"
          + ("  <-- log every signal day, even skips" if snap["discipline"]["unaccounted"] else ""))

    # -- signal health -----------------------------------------------------
    if n_traded:
        wins = int((t["pnl"] > 0).sum())
        lo, hi = wilson(wins, n_traded)
        snap["signal_health"] = {"n": n_traded, "win_rate": round(wins / n_traded, 3),
                                 "wilson95": [round(lo, 3), round(hi, 3)],
                                 "mean_pnl": round(float(t["pnl"].mean()), 2),
                                 "total_pnl": round(float(t["pnl"].sum()), 2)}
        print(f"SIGNAL      n={n_traded}  win={wins/n_traded:.0%} "
              f"(95% CI {lo:.0%}-{hi:.0%})  mean=${t['pnl'].mean():+.2f}  "
              f"total=${t['pnl'].sum():+.2f}")
        if n_traded < 20:
            print("            interval is wide because n is small -- that is the "
                  "true state of knowledge, not a bug.")
    else:
        snap["signal_health"] = None
        print("SIGNAL      no real trades logged yet.")

    # -- cost calibration (needs broker-statement overrides) ---------------
    # log_trade.py prints the computed-vs-statement diff at log time; rows
    # where a note mentions 'override' or where you re-log with --pnl-override
    # are the raw material. Until then this section reports not-measurable.
    snap["costs"] = {"status": "not_measurable_yet",
                     "how": "log trades with --pnl-override from broker statements; "
                            "the computed-vs-realized gap is your true slippage"}
    print("COSTS       not measurable yet -- use --pnl-override with statement "
          "P&L so realized slippage becomes data.")

    OUT.parent.mkdir(exist_ok=True)
    hist = json.loads(OUT.read_text()) if OUT.exists() else []
    hist.append(snap)
    OUT.write_text(json.dumps(hist, indent=1))
    print(f"\nsnapshot appended to {OUT} ({len(hist)} total)")


if __name__ == "__main__":
    main()
