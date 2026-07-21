"""Loader + data-quality audit + session labeling.

Handles: CSV or Parquet; 'datetime' or 'timestamp' column names; timezone-naive
stamps (localized per config -- run the grep test to determine the source tz:
missing 17:xx hours every weekday => stamps are ET; missing 22:xx => UTC)."""
import pandas as pd

REQUIRED = ["timestamp", "open", "high", "low", "close", "volume"]


def load_ohlcv(path: str, tz: str, naive_stamps_are: str = "America/New_York") -> pd.DataFrame:
    df = pd.read_parquet(path) if str(path).endswith(".parquet") else pd.read_csv(path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "datetime" in df.columns and "timestamp" not in df.columns:
        df = df.rename(columns={"datetime": "timestamp"})
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}. Found: {list(df.columns)}")
    ts = pd.to_datetime(df["timestamp"], errors="coerce")
    if ts.isna().any():
        raise ValueError(f"{ts.isna().sum()} unparseable timestamps")
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize(naive_stamps_are, ambiguous="NaT", nonexistent="NaT")
        if ts.isna().any():
            raise ValueError(
                "Timestamps fall in a DST gap -- the naive_stamps_are assumption "
                "is wrong. Re-run the timezone grep test.")
    df["timestamp"] = ts.dt.tz_convert(tz)
    df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    return label_sessions(df)


def label_sessions(df: pd.DataFrame) -> pd.DataFrame:
    t = df["timestamp"].dt
    df["date_et"] = t.date
    # CME trading day: bars from 18:00 ET onward belong to the NEXT day's session
    tradeday = df["timestamp"].where(t.hour < 18, df["timestamp"] + pd.Timedelta(days=1))
    df["trade_day"] = tradeday.dt.date
    hm = t.hour * 60 + t.minute

    def block(m):
        if 570 <= m < 660:
            return "open_0930_1100"
        if 660 <= m < 810:
            return "lunch_1100_1330"
        if 810 <= m < 900:
            return "pm_1330_1500"
        if 900 <= m < 960:
            return "power_1500_1600"
        if 960 <= m < 1020:
            return "close_1600_1700"
        return "overnight"

    df["session_block"] = [block(m) for m in hm]
    df["is_rth"] = (hm >= 570) & (hm < 960)
    return df


def audit(df: pd.DataFrame) -> dict:
    """Run BEFORE trusting any backtest, especially on unverified free data."""
    gaps = df["timestamp"].diff().dt.total_seconds().div(60)
    big_gaps = int((gaps[df["session_block"] != "overnight"] > 5).sum())
    zero_vol = int((df["volume"] <= 0).sum())
    bad_ohlc = int(((df["high"] < df[["open", "close", "low"]].max(axis=1)) |
                    (df["low"] > df[["open", "close", "high"]].min(axis=1))).sum())
    jumps = df["close"].pct_change().abs()
    suspicious_jumps = int((jumps > 0.03).sum())  # >3% in 1 min: halt, error, or bad roll stitch
    return {"rows": len(df),
            "start": str(df["timestamp"].iloc[0]),
            "end": str(df["timestamp"].iloc[-1]),
            "intraday_gaps_gt_5min": big_gaps,
            "zero_volume_bars": zero_vol,
            "invalid_ohlc_bars": bad_ohlc,
            "one_min_moves_gt_3pct": suspicious_jumps}
