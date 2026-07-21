"""Free rolling 1-min cache from Yahoo Finance. Run scripts/update_cache.py at
least every ~5 days or gaps become permanent (Yahoo serves ~7 days of 1m data).
Provenance note: Yahoo ES=F prints are unofficial; audit() runs on every update."""
from pathlib import Path

import pandas as pd


def update_cache(store_path: str, ticker: str = "ES=F") -> dict:
    import yfinance as yf   # pip install yfinance
    new = yf.download(ticker, interval="1m", period="7d",
                      auto_adjust=False, progress=False)
    if new.empty:
        raise RuntimeError("Yahoo returned no data -- check ticker/connectivity.")
    if isinstance(new.columns, pd.MultiIndex):
        new.columns = [c[0].lower() for c in new.columns]
    else:
        new.columns = [c.lower() for c in new.columns]
    new = (new.rename_axis("timestamp").reset_index()
              [["timestamp", "open", "high", "low", "close", "volume"]])
    new["timestamp"] = pd.to_datetime(new["timestamp"], utc=True)

    p = Path(store_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        old = pd.read_parquet(p)
        merged = pd.concat([old, new])
    else:
        old, merged = None, new
    merged = (merged.drop_duplicates("timestamp")
                    .sort_values("timestamp").reset_index(drop=True))
    gap_min = merged["timestamp"].diff().dt.total_seconds().div(60)
    worst = float(gap_min.max()) if len(merged) > 1 else 0.0
    merged.to_parquet(p, index=False)
    return {"rows_total": len(merged),
            "rows_added": len(merged) - (len(old) if old is not None else 0),
            "span": f'{merged["timestamp"].iloc[0]} -> {merged["timestamp"].iloc[-1]}',
            "worst_gap_minutes": worst,
            "warning": ("GAP >2 days -- you missed update runs; hole is permanent"
                        if worst > 2880 else None)}
