"""Serialize the latest signal + log into signal.json for the Sentry dashboard.

This script performs NO trading computation. It only READS signals_log.csv,
which scripts/signal_check.py writes, and reformats it as JSON.

signal_check.py is self-contained: it downloads its own daily bars from Yahoo
on every run and does not read any local price file. So freshness here is
measured off the signal's own signal_date / logged_at, not off any cache.
The 1-min data files are research inputs for the quantlab backtests and are
reported below as context only.
"""
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path("signals_log.csv")
OUT_PATH = Path("signal.json")
MAX_ROWS = 250

# Exact schema written by signal_check.py (as of the version reviewed).
COLS = {"date": "signal_date", "verdict": "trade_next_day", "rsi": "rsi2",
        "close": "close", "down3": "down3", "logged": "logged_at"}

def norm_date(v):
    """'7/22/2026' and '2026-07-22' both -> '2026-07-22'; unknown -> unchanged."""
    v = (v or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(v, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return v or None


TRUE = {"true", "t", "yes", "y", "1", "trade"}
FALSE = {"false", "f", "no", "n", "0", "no trade", "no-trade"}


def main() -> int:
    if not LOG_PATH.exists():
        print(f"ERROR: {LOG_PATH} not found. It must be committed to the repo.",
              file=sys.stderr)
        return 1

    with LOG_PATH.open(newline="") as f:
        rows = [r for r in csv.reader(f) if any(c.strip() for c in r)]
    if len(rows) < 2:
        print("ERROR: signals_log.csv has a header but no data rows.", file=sys.stderr)
        return 1

    header, data = rows[0], rows[1:]
    idx = {h.strip(): i for i, h in enumerate(header)}

    missing = [c for c in (COLS["date"], COLS["verdict"]) if c not in idx]
    if missing:
        print(f"ERROR: signals_log.csv is missing required column(s): {missing}",
              file=sys.stderr)
        print(f"Actual header: {header}", file=sys.stderr)
        print("signal_check.py's output format changed. Update COLS at the top "
              "of scripts/export_signal.py to match.", file=sys.stderr)
        return 1

    def cell(row, key):
        col = COLS.get(key)
        if col is None or col not in idx or idx[col] >= len(row):
            return None
        v = row[idx[col]].strip()
        return v or None

    def as_float(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    def verdict_of(row):
        raw = cell(row, "verdict")
        low = (raw or "").strip().lower()
        if low in TRUE:
            return "TRADE"
        if low in FALSE:
            return "NO-TRADE"
        return "UNKNOWN"

    last = data[-1]
    if verdict_of(last) == "UNKNOWN":
        print(f"ERROR: could not read the verdict value {cell(last,'verdict')!r} "
              f"in column '{COLS['verdict']}' as true/false.", file=sys.stderr)
        return 1

    # RSI2 series for the chart. The log records no P&L, so there is no equity
    # curve to draw -- the dashboard is told this explicitly rather than shown
    # an invented one.
    pts = []
    for r in data[-MAX_ROWS:]:
        v = as_float(cell(r, "rsi"))
        if v is not None:
            pts.append({"date": norm_date(cell(r, "date")), "value": v,
                        "trade": verdict_of(r) == "TRADE"})

    # Research data files (quantlab backtest inputs) -- informational only.
    research = None
    cands = sorted(Path("data").glob("*.csv")) + sorted(Path("data").glob("**/*.parquet"))
    if cands:
        p = max(cands, key=lambda x: x.stat().st_size)
        research = {"file": p.name, "bytes": p.stat().st_size}

    out = {
        "schema": 2,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of": norm_date(cell(last, "date")),
        "verdict": verdict_of(last),
        "rsi2": as_float(cell(last, "rsi")),
        "rsi2_threshold": 15,
        "close": as_float(cell(last, "close")),
        "down3": (cell(last, "down3") or "").strip().lower() in TRUE,
        "logged_at": cell(last, "logged"),
        "has_pnl": False,
        "research_data": research,
        "log": {"columns": header,
                "rows": [[norm_date(c) if i == idx[COLS["date"]] else c
                          for i, c in enumerate(r)] for r in data[-MAX_ROWS:]],
                "total_rows": len(data)},
        "series": {"column": COLS["rsi"], "kind": "rsi", "points": pts} if pts else None,
        "columns": COLS,
    }
    OUT_PATH.write_text(json.dumps(out, indent=1))
    print(f"wrote {OUT_PATH}: as_of={out['as_of']} verdict={out['verdict']} "
          f"rsi2={out['rsi2']} log_rows={len(data)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
