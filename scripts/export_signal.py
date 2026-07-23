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
CONFIG_PATH = Path("config/default.yaml")
UPDATER_PATH = Path("data/cache/es_1min.parquet")  # what update_cache.py writes
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


def config_data_path():
    """Return the price-data file the signal actually reads, per config.

    Falls back to a glob if the configured name doesn't exist on disk (the
    repo config and the real filename have differed before -- e.g. a stray
    double '.csv' extension)."""
    p = None
    if CONFIG_PATH.exists():
        try:
            import yaml
            cfg = yaml.safe_load(CONFIG_PATH.read_text()) or {}
            raw = (cfg.get("data") or {}).get("path")
            if raw:
                p = Path(raw)
        except Exception as e:
            print(f"WARNING: could not parse {CONFIG_PATH}: {e}", file=sys.stderr)
    if p and p.exists():
        return p
    if p:
        # tolerate exact-name drift: match on the stem before the extensions
        stem = p.name.split(".")[0]
        for cand in sorted(Path("data").glob(stem + "*")):
            print(f"NOTE: config points at '{p}' which is absent; using the "
                  f"closest file on disk: '{cand}'", file=sys.stderr)
            return cand
    for cand in sorted(Path("data").glob("*.csv")) + sorted(Path("data").glob("**/*.parquet")):
        print(f"NOTE: no configured data path; falling back to '{cand}'", file=sys.stderr)
        return cand
    return p


def last_bar(path: Path):
    """(iso_utc_timestamp, row_count) for a CSV or Parquet bar file."""
    try:
        if path.suffix.lower() == ".parquet":
            import pyarrow.parquet as pq
            t = pq.read_table(path, columns=["timestamp"])
            if not t.num_rows:
                return None, 0
            ts = t.column("timestamp")[-1].as_py()
        else:
            import pandas as pd
            df = pd.read_csv(path)
            df.columns = [str(c).strip().lower() for c in df.columns]
            col = "timestamp" if "timestamp" in df.columns else (
                  "datetime" if "datetime" in df.columns else df.columns[0])
            if not len(df):
                return None, 0
            ts = pd.to_datetime(df[col], errors="coerce").dropna().max().to_pydatetime()
            return (ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None
                    else ts.astimezone(timezone.utc)).isoformat(), len(df)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc).isoformat(), t.num_rows
    except Exception as e:
        print(f"WARNING: could not read last bar from {path}: {e}", file=sys.stderr)
        return None, None


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
    read_path = config_data_path()      # the file the SIGNAL actually reads
    cache_last_bar, cache_rows, cache_file = (None, None, None)
    if read_path and read_path.exists():
        cache_file = str(read_path)
        cache_last_bar, cache_rows = last_bar(read_path)
    else:
        print(f"WARNING: config data path not found on disk: {read_path}",
              file=sys.stderr)

    # If update_cache.py writes somewhere other than what the signal reads,
    # the scheduled job can succeed every night while the signal silently
    # runs on frozen data. Surface that in the dashboard rather than hide it.
    cache_warning = None
    if read_path and UPDATER_PATH.resolve() != read_path.resolve():
        upd_bar, _ = last_bar(UPDATER_PATH) if UPDATER_PATH.exists() else (None, None)
        cache_warning = (
            f"PIPELINE SPLIT: update_cache.py writes {UPDATER_PATH} "
            f"(last bar {upd_bar or 'n/a'}) but the signal reads {read_path} "
            f"(last bar {cache_last_bar or 'n/a'}). Refreshing one does not "
            f"refresh the other.")
        print("WARNING: " + cache_warning, file=sys.stderr)

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
        "cache_file": cache_file,
        "cache_warning": cache_warning,
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
