import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rma(s: pd.Series, n: int) -> pd.Series:          # Wilder smoothing (Pine ta.rma)
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


def rsi(close: pd.Series, n: int) -> pd.Series:
    ch = close.diff()
    up = rma(ch.clip(lower=0), n)
    dn = rma((-ch).clip(lower=0), n)
    out = 100 - 100 / (1 + up / dn)
    return out.where(dn != 0, 100.0).fillna(50.0)


def cci(close: pd.Series, high: pd.Series, low: pd.Series, n: int) -> pd.Series:
    tp = (high + low + close) / 3
    sma = tp.rolling(n).mean()
    mad = tp.rolling(n).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (tp - sma) / (0.015 * mad)


def zscore(close: pd.Series, n: int) -> pd.Series:
    m = ema(close, n)
    sd = close.rolling(n).std(ddof=0)
    return (close - m) / sd


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(),
                    (df["low"] - pc).abs()], axis=1).max(axis=1)
    return rma(tr, n)
