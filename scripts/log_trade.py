"""Record a REAL executed trade. This is the data that unlocks evalsim.

Usage (after you take the trade the signal called):

  python scripts/log_trade.py --date 2026-07-24 --side long --contracts 10 \
      --entry 7530.25 --exit 7541.50 --reason time_exit

  # a day you took the signal but got stopped:
  python scripts/log_trade.py --date 2026-07-28 --side long --contracts 10 \
      --entry 7502.00 --exit 7351.75 --reason stop

  # a signal day you DID NOT trade still matters for honesty, log it:
  python scripts/log_trade.py --date 2026-07-30 --skipped --note "travel"

Writes trades_log.csv (one row per fill) and regenerates daily_pnl.csv
(net P&L per traded day). evalsim reads daily_pnl.csv and refuses to run
below 15 traded days -- run scripts/run_evalsim.py to check progress.

P&L is computed from exchange tick math + your configured commissions, so the
number matches what the account statement should show BEFORE exchange fees you
haven't modeled. If your broker statement disagrees materially, log the
statement's number with --pnl-override and note why -- realized costs are data.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, ".")
from quantlab.contracts import get_spec

TRADES = Path("trades_log.csv")
DAILY = Path("daily_pnl.csv")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="trade date YYYY-MM-DD")
    ap.add_argument("--side", choices=["long", "short"], default="long")
    ap.add_argument("--instrument", default=None, help="ES or MES (default: config live.instrument)")
    ap.add_argument("--contracts", type=int, default=None)
    ap.add_argument("--entry", type=float, default=None)
    ap.add_argument("--exit", dest="exit_px", type=float, default=None)
    ap.add_argument("--reason", choices=["stop", "target", "time_exit", "manual"],
                    default="time_exit")
    ap.add_argument("--pnl-override", type=float, default=None,
                    help="use broker-statement P&L instead of computed")
    ap.add_argument("--skipped", action="store_true",
                    help="signal day you did not trade (logged, excluded from P&L)")
    ap.add_argument("--note", default="")
    a = ap.parse_args()

    cfg = yaml.safe_load(open("config/default.yaml"))
    instrument = (a.instrument or cfg["live"]["instrument"]).upper()
    spec = get_spec(instrument)
    comm = cfg["costs"]["commission_rt_es"] if instrument == "ES" \
        else cfg["costs"]["commission_rt_mes"]

    if a.skipped:
        pnl, entry, exit_px, n = None, None, None, 0
    else:
        for f, name in ((a.contracts, "--contracts"), (a.entry, "--entry"),
                        (a.exit_px, "--exit")):
            if f is None:
                ap.error(f"{name} is required unless --skipped")
        n = a.contracts
        cap = cfg["execution"]["max_contracts"][instrument]
        if n > cap:
            print(f"WARNING: {n} contracts exceeds configured cap of {cap} {instrument}. "
                  f"Logging anyway -- but check what you actually did.")
        entry, exit_px = a.entry, a.exit_px
        side = 1 if a.side == "long" else -1
        gross = side * (exit_px - entry) / spec.tick_size * spec.tick_value * n
        pnl = round(gross - comm * n, 2)
        if a.pnl_override is not None:
            print(f"computed P&L ${pnl:+.2f} overridden by statement ${a.pnl_override:+.2f} "
                  f"(diff ${a.pnl_override - pnl:+.2f} = realized cost slippage, kept on record)")
            pnl = a.pnl_override

    row = pd.DataFrame([{"date": a.date, "instrument": instrument, "side": a.side,
                         "contracts": n, "entry": entry, "exit": exit_px,
                         "reason": ("skipped" if a.skipped else a.reason),
                         "pnl": pnl, "note": a.note,
                         "logged_at": pd.Timestamp.now().isoformat()}])
    out = pd.concat([pd.read_csv(TRADES), row]) if TRADES.exists() else row
    out.to_csv(TRADES, index=False)

    traded = out[out["reason"] != "skipped"].dropna(subset=["pnl"])
    daily = traded.groupby("date", as_index=False)["pnl"].sum()
    daily.to_csv(DAILY, index=False)
    print(f"logged. traded days on record: {len(daily)} "
          f"({max(0, 15 - len(daily))} more needed before evalsim will run)")
    if pnl is not None:
        print(f"this trade: {a.side} {n} {instrument} {entry} -> {exit_px}  P&L ${pnl:+.2f}")


if __name__ == "__main__":
    main()
