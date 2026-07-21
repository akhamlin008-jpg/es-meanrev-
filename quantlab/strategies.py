"""Signal generators. Both emit +1/-1/0 per bar; geometry (stop/target/time-stop)
is applied uniformly by the engine so strategies compare like-for-like.

Note: the original Pine indicator defines ENTRIES ONLY -- it has no exit logic --
so its exits here come from the shared geometry module. That is a design decision
forced by the source material, and it is flagged, not hidden."""
import pandas as pd

from . import indicators as ind


def signals_zscore_mr(df: pd.DataFrame, p: dict) -> pd.Series:
    """Baseline/null model: enter when z-score re-crosses back inside the band
    (reversion confirmation, avoids catching the falling knife on first touch)."""
    z = ind.zscore(df["close"], p["lookback"])
    long_e = (z > -p["z_entry"]) & (z.shift() <= -p["z_entry"])
    short_e = (z < p["z_entry"]) & (z.shift() >= p["z_entry"])
    return pd.Series(0, index=df.index).mask(long_e, 1).mask(short_e, -1)


def signals_pine_port(df: pd.DataFrame, p: dict) -> pd.Series:
    """Faithful port of 'Extreme Entry with Mean Reversion and Trend Filter'."""
    close = df["close"]
    if p["entry_source"] == "Momentum":
        osc = close - close.shift(p["ccimom_length"])
    else:
        osc = ind.cci(close, df["high"], df["low"], p["ccimom_length"])
    cross_up = (osc > 0) & (osc.shift() <= 0)
    cross_dn = (osc < 0) & (osc.shift() >= 0)

    r = ind.rsi(close, p["rsi_length"])
    oversold_ago = (r <= p["rsi_oversold"])
    overbought_ago = (r >= p["rsi_overbought"])
    for k in (1, 2, 3):
        oversold_ago |= (r.shift(k) <= p["rsi_oversold"])
        overbought_ago |= (r.shift(k) >= p["rsi_overbought"])

    long_c, short_c = cross_up & oversold_ago, cross_dn & overbought_ago
    if p["use_divergence"]:
        # NOTE: the Pine source's "divergence" is only a 3-bar RSI V/^ shape,
        # not true price/RSI divergence. Ported as written; improving it is a
        # later hypothesis to test, not a silent "fix".
        long_c &= (r > r.shift(1)) & (r.shift(1) < r.shift(2))
        short_c &= (r < r.shift(1)) & (r.shift(1) > r.shift(2))

    m = ind.ema(close, p["mr_lookback"])
    sd = close.rolling(p["mr_lookback"]).std(ddof=0)
    up, lo = m + p["band_mult"] * sd, m - p["band_mult"] * sd
    if p["mr_filter"] == "range":
        inside = (close > lo) & (close < up)
        long_c &= inside
        short_c &= inside
    elif p["mr_filter"] == "extreme":
        outside = (close < lo) | (close > up)
        long_c &= outside
        short_c &= outside

    if p["trend_filter"]:
        t = ind.ema(close, p["trend_ema"])
        long_c &= close > t
        short_c &= close < t

    return pd.Series(0, index=df.index).mask(long_c, 1).mask(short_c, -1)


REGISTRY = {"zscore_mr": signals_zscore_mr, "pine_port": signals_pine_port}
