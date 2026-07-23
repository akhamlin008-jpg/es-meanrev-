"""Serialize the latest signal + log into signal.json for the Sentry dashboard.

This script performs NO trading computation. It only READS:
  - signals_log.csv        (written by scripts/signal_check.py — single source of truth)
  - data/cache/es_1min.parquet  (for the last-bar timestamp = data freshness)
and writes signal.json.

It auto-detects column names from the CSV header. If it cannot find a verdict
column it exits non-zero and prints the actual header, so the CI run fails
loudly instead of publishing a wrong or empty signal.
"""
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path("signals_log.csv")
CACHE_PATH = Path("data/cache/es_1min.parquet")
OUT_PATH = Path("signal.json")
MAX_ROWS = 250  # most recent log rows to embed

# Candidate column names, matched case-insensitively after stripping _-/space.
DATE_KEYS = ("date", "asof", "as_of", "session", "day", "timestamp", "signaldate")
VERDICT_KEYS = ("verdict", "decision", "signal", "action", "trade", "result")
RSI_KEYS = ("rsi2", "rsi", "rsi_2")
EQUITY_KEYS = ("equity", "cumpnl", "cum_pnl", "pnlcum", "balance", "cumulative",
               "equitycurve", "paperequity")


def norm(name: str) -> str:
    return name.strip().lower().replace("_", "").replace("-", "").replace(" ", "")


def find_col(header, candidates):
    normed = {norm(h): h for h in header}
    for c in candidates:
        if norm(c) in normed:
            return normed[norm(c)]
    # fallback: substring match (e.g. "rsi2_close")
    for h in header:
        if any(norm(c) in norm(h) for c in candidates):
            return h
    return None


def normalize_verdict(raw: str) -> str:
    v = (raw or "").strip().upper()
    # check "NO" first: "NO TRADE" / "NO-TRADE" also contain the word TRADE
    if "NO" in v:
        return "NO-TRADE"
    if "TRADE" in v or v in ("LONG", "BUY", "ENTER", "YES", "TRUE", "1"):
        return "TRADE"
    return v or "UNKNOWN"


def main() -> int:
    if not LOG_PATH.exists():
        print(f"ERROR: {LOG_PATH} not found. Run scripts/signal_check.py first "
              f"(and make sure the file is committed to the repo).", file=sys.stderr)
        return 1

    with LOG_PATH.open(newline="") as f:
        reader = csv.reader(f)
        rows = [r for r in reader if any(cell.strip() for cell in r)]
    if len(rows) < 2:
        print("ERROR: signals_log.csv has a header but no data rows.", file=sys.stderr)
        return 1

    header, data = rows[0], rows[1:]
    date_col = find_col(header, DATE_KEYS)
    verdict_col = find_col(header, VERDICT_KEYS)
    rsi_col = find_col(header, RSI_KEYS)
    equity_col = find_col(header, EQUITY_KEYS)

    if verdict_col is None:
        print("ERROR: could not identify a verdict/decision column in signals_log.csv.",
              file=sys.stderr)
        print(f"Actual header: {header}", file=sys.stderr)
        print("Fix: rename the column to 'verdict' or add its name to VERDICT_KEYS "
              "in scripts/export_signal.py.", file=sys.stderr)
        return 1

    idx = {h: i for i, h in enumerate(header)}
    last = data[-1]

    def cell(row, col):
        if col is None or idx[col] >= len(row):
            return None
        return row[idx[col]].strip()

    def as_float(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    # ---- cache freshness -------------------------------------------------
    cache_last_bar = None
    cache_rows = None
    if CACHE_PATH.exists():
        try:
            import pyarrow.parquet as pq
            t = pq.read_table(CACHE_PATH, columns=["timestamp"])
            cache_rows = t.num_rows
            if cache_rows:
                ts = t.column("timestamp")[-1].as_py()
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                cache_last_bar = ts.astimezone(timezone.utc).isoformat()
        except Exception as e:  # freshness is metadata; never block the export
            print(f"WARNING: could not read cache last-bar timestamp: {e}",
                  file=sys.stderr)
    else:
        print(f"WARNING: {CACHE_PATH} not found; cache freshness unknown.",
              file=sys.stderr)

    # ---- chart series (display only, no computation) ---------------------
    series_col = equity_col or rsi_col
    series = None
    if series_col is not None:
        pts = []
        for r in data[-MAX_ROWS:]:
            v = as_float(cell(r, series_col))
            if v is not None:
                pts.append({"date": cell(r, date_col), "value": v})
        if pts:
            series = {"column": series_col,
                      "kind": "equity" if equity_col else "rsi",
                      "points": pts}

    out = {
        "schema": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of": cell(last, date_col),
        "verdict": normalize_verdict(cell(last, verdict_col)),
        "verdict_raw": cell(last, verdict_col),
        "rsi2": as_float(cell(last, rsi_col)),
        "cache_last_bar_utc": cache_last_bar,
        "cache_rows": cache_rows,
        "log": {
            "columns": header,
            "rows": data[-MAX_ROWS:],
            "total_rows": len(data),
        },
        "series": series,
        "detected_columns": {"date": date_col, "verdict": verdict_col,
                             "rsi": rsi_col, "equity": equity_col},
    }
    OUT_PATH.write_text(json.dumps(out, indent=1))
    print(f"wrote {OUT_PATH}: as_of={out['as_of']} verdict={out['verdict']} "
          f"rsi2={out['rsi2']} log_rows={len(data)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
