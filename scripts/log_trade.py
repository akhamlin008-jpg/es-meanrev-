"""Record a REAL executed trade. This is the data that unlocks evalsim.

TWO WAYS TO RUN:

1. INTERACTIVE (easiest -- just run it, it asks you questions):

     python scripts/log_trade.py

   It reads the latest signal to pre-fill the date and side, then prompts for
   the only things it CANNOT know: your actual fills. Press Enter to accept a
   pre-filled default shown in [brackets].

2. FLAGS (for scripting / when you already know the values):

     python scripts/log_trade.py --date 2026-07-24 --side long --contracts 10 \
         --entry 7530.25 --exit 7541.50 --reason time_exit

     # a signal day you DID NOT trade -- log it anyway, honesty matters:
     python scripts/log_trade.py --date 2026-07-30 --skipped --note "travel"

WHY THIS IS MANUAL: the bot did not place your order, so it has no way to know
your real entry, exit, or size. That is exactly the data evalsim needs -- the
gap between what the rules would do (the backtest) and what your fills actually
did. Auto-filling "what the rules should have done" would just copy the
backtest and make evalsim run on fiction. So the fills come from you.

If your broker can export a fills/trades CSV, that is the one path to real
automation -- tell me the export format and it can be wired up; formats
differ, so it is not guessed here.

Writes trades_log.csv (one row per fill) and regenerates daily_pnl.csv.
evalsim reads daily_pnl.csv and refuses to run below 15 traded days.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, ".")
from quantlab.contracts import get_spec

TRADES = Path("trades_log.csv")
DAILY = Path("daily_pnl.csv")
REASONS = ["stop", "target", "time_exit", "manual"]


def compute_pnl(side, entry, exit_px, n, spec, comm):
    s = 1 if side == "long" else -1
    gross = s * (exit_px - entry) / spec.tick_size * spec.tick_value * n
    return round(gross - comm * n, 2)


def write_and_report(row):
    df = pd.DataFrame([row])
    out = pd.concat([pd.read_csv(TRADES), df]) if TRADES.exists() else df
    out.to_csv(TRADES, index=False)
    traded = out[out["reason"] != "skipped"].dropna(subset=["pnl"])
    daily = traded.groupby("date", as_index=False)["pnl"].sum()
    daily.to_csv(DAILY, index=False)
    print(f"\nlogged to {TRADES}. traded days on record: {len(daily)} "
          f"({max(0, 15 - len(daily))} more before evalsim will run).")
    if row["pnl"] is not None:
        print(f"this trade: {row['side']} {row['contracts']} {row['instrument']} "
              f"{row['entry']} -> {row['exit']}  P&L ${row['pnl']:+.2f}")


def latest_signal_hint():
    """Pre-fill date/side from signal.json (preferred) or signals_log.csv."""
    hint = {}
    try:
        j = json.loads(Path("signal.json").read_text())
        hint["date"] = j.get("as_of")
        if j.get("verdict") == "TRADE":
            hint["side"] = "short" if j.get("sig") == -1 else "long"
    except Exception:
        pass
    if "date" not in hint and Path("signals_log.csv").exists():
        try:
            s = pd.read_csv("signals_log.csv")
            last = s.iloc[-1]
            hint.setdefault("date", str(last.get("signal_date")))
            if "sig" in s.columns:
                hint["side"] = {1: "long", -1: "short"}.get(int(last["sig"]), "long")
        except Exception:
            pass
    return hint


def ask(prompt, default=None, cast=str, choices=None):
    d = f" [{default}]" if default not in (None, "") else ""
    while True:
        raw = input(f"{prompt}{d}: ").strip()
        if raw == "" and default is not None:
            return default
        if raw == "" and default is None:
            print("  (required)"); continue
        try:
            val = cast(raw)
        except ValueError:
            print(f"  not a valid {cast.__name__}"); continue
        if choices and val not in choices:
            print(f"  choose one of: {', '.join(map(str, choices))}"); continue
        return val


def yes(prompt, default=True):
    d = "Y/n" if default else "y/N"
    raw = input(f"{prompt} [{d}]: ").strip().lower()
    return default if raw == "" else raw in ("y", "yes")


def interactive(cfg):
    hint = latest_signal_hint()
    print("=== log a trade (press Enter to accept [defaults]) ===")
    if hint.get("date"):
        print(f"latest signal: date={hint.get('date')} side={hint.get('side','?')}")
    date = ask("Trade date (YYYY-MM-DD)", hint.get("date"))

    if not yes("Did you actually take this trade?", default=True):
        note = ask("Reason skipped (e.g. travel, no fill)", "", cast=str)
        write_and_report({"date": date, "instrument": cfg["live"]["instrument"].upper(),
                          "side": hint.get("side", "long"), "contracts": 0,
                          "entry": None, "exit": None, "reason": "skipped",
                          "pnl": None, "note": note,
                          "logged_at": pd.Timestamp.now().isoformat()})
        return

    instrument = ask("Instrument", cfg["live"]["instrument"].upper(),
                     choices=["ES", "MES"], cast=lambda x: x.upper())
    spec = get_spec(instrument)
    comm = cfg["costs"]["commission_rt_es"] if instrument == "ES" \
        else cfg["costs"]["commission_rt_mes"]
    cap = cfg["execution"]["max_contracts"][instrument]

    side = ask("Side", hint.get("side", "long"), choices=["long", "short"])
    n = ask("Contracts filled", cast=int)
    if n > cap:
        print(f"  note: {n} exceeds your configured cap of {cap} {instrument} "
              f"-- logging what you did, but double-check.")
    entry = ask("Entry price (your actual fill)", cast=float)
    exit_px = ask("Exit price (your actual fill)", cast=float)
    reason = ask("Exit reason", "time_exit", choices=REASONS)

    pnl = compute_pnl(side, entry, exit_px, n, spec, comm)
    print(f"\ncomputed P&L from your fills: ${pnl:+.2f}")
    if yes("Override with the P&L shown on your broker statement?", default=False):
        stmt = ask("Broker-statement P&L (signed, e.g. -137.50)", cast=float)
        print(f"  realized slippage vs computed: ${stmt - pnl:+.2f} (kept on record)")
        pnl = stmt
    note = ask("Note (optional)", "", cast=str)
    write_and_report({"date": date, "instrument": instrument, "side": side,
                      "contracts": n, "entry": entry, "exit": exit_px,
                      "reason": reason, "pnl": pnl, "note": note,
                      "logged_at": pd.Timestamp.now().isoformat()})


def flag_mode(a, cfg):
    instrument = (a.instrument or cfg["live"]["instrument"]).upper()
    spec = get_spec(instrument)
    comm = cfg["costs"]["commission_rt_es"] if instrument == "ES" \
        else cfg["costs"]["commission_rt_mes"]
    if a.skipped:
        row = {"date": a.date, "instrument": instrument, "side": a.side,
               "contracts": 0, "entry": None, "exit": None, "reason": "skipped",
               "pnl": None, "note": a.note, "logged_at": pd.Timestamp.now().isoformat()}
    else:
        for f, name in ((a.contracts, "--contracts"), (a.entry, "--entry"),
                        (a.exit_px, "--exit")):
            if f is None:
                raise SystemExit(f"error: {name} is required unless --skipped")
        cap = cfg["execution"]["max_contracts"][instrument]
        if a.contracts > cap:
            print(f"WARNING: {a.contracts} contracts exceeds cap of {cap} {instrument}.")
        pnl = compute_pnl(a.side, a.entry, a.exit_px, a.contracts, spec, comm)
        if a.pnl_override is not None:
            print(f"computed ${pnl:+.2f} overridden by statement ${a.pnl_override:+.2f} "
                  f"(diff ${a.pnl_override - pnl:+.2f} = realized slippage)")
            pnl = a.pnl_override
        row = {"date": a.date, "instrument": instrument, "side": a.side,
               "contracts": a.contracts, "entry": a.entry, "exit": a.exit_px,
               "reason": a.reason, "pnl": pnl, "note": a.note,
               "logged_at": pd.Timestamp.now().isoformat()}
    write_and_report(row)


def main():
    cfg = yaml.safe_load(open("config/default.yaml"))
    if len(sys.argv) == 1:
        try:
            interactive(cfg)
        except (KeyboardInterrupt, EOFError):
            print("\naborted -- nothing logged.")
        return
    ap = argparse.ArgumentParser(description="Log a real executed trade.")
    ap.add_argument("--date", required=True, help="trade date YYYY-MM-DD")
    ap.add_argument("--side", choices=["long", "short"], default="long")
    ap.add_argument("--instrument", default=None, help="ES or MES")
    ap.add_argument("--contracts", type=int, default=None)
    ap.add_argument("--entry", type=float, default=None)
    ap.add_argument("--exit", dest="exit_px", type=float, default=None)
    ap.add_argument("--reason", choices=REASONS, default="time_exit")
    ap.add_argument("--pnl-override", type=float, default=None)
    ap.add_argument("--skipped", action="store_true")
    ap.add_argument("--note", default="")
    flag_mode(ap.parse_args(), cfg)


if __name__ == "__main__":
    main()
