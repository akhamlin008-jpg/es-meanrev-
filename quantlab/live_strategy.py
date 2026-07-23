"""SINGLE SOURCE OF TRUTH for the live trading rules.

This module is imported by BOTH:
  - scripts/signal_check.py      (the nightly live signal)
  - scripts/backtest_live_rules.py (the backtest of those exact rules)

If a rule changes, it changes here, and both the live signal and the backtest
change together. That is the entire point: nothing is live that was never
tested, and nothing is tested that isn't what goes live.

Rules are loaded from config/default.yaml `live:` section, so the config file
is the written contract and this module is its executable form.

SHORT SIDE: implemented but OFF by default (live.enable_shorts: false).
Index mean-reversion is not symmetric -- equities drift up, so "fade the
oversold" and "fade the overbought" are different bets. The short trigger
must show positive drift-adjusted results in validate_spy.py AND in
backtest_live_rules.py before enable_shorts is flipped. Do not enable it
because the code exists; enable it because the test passed.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


# ---------------------------------------------------------------- indicators

def rsi2(close: pd.Series, period: int = 2) -> pd.Series:
    """Connors-style RSI on closes, Wilder smoothing (ewm alpha=1/period).
    This is THE implementation. signal_check.py and the backtest both call it;
    validate_spy.py imports it too. Do not re-implement it anywhere."""
    ch = close.diff()
    up = ch.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    dn = (-ch).clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


# ------------------------------------------------------------------- rules

@dataclass(frozen=True)
class LiveRules:
    """The complete rule set, one object. Defaults mirror config/default.yaml;
    always construct via from_config so the YAML stays authoritative."""
    rsi_period: int = 2
    rsi_long_below: float = 15.0     # long trigger: RSI2 < 15 ...
    consec_down_days: int = 3        # ... OR three consecutive down closes
    enable_shorts: bool = False
    rsi_short_above: float = 85.0    # short trigger: RSI2 > 85 ...
    consec_up_days: int = 3          # ... OR three consecutive up closes
    entry_time: str = "10:00"        # ET, next session, market order
    exit_time: str = "15:55"         # ET hard flatten
    stop_pct: float = 0.02           # hard stop, % of entry price
    instrument: str = "MES"          # what you actually trade

    @classmethod
    def from_config(cls, cfg: dict) -> "LiveRules":
        c = cfg.get("live", {})
        return cls(**{k: c[k] for k in cls.__dataclass_fields__ if k in c})


# ------------------------------------------------------------------ signal

def daily_signal(daily_close: pd.Series, rules: LiveRules) -> pd.DataFrame:
    """Vectorized signal on a DAILY close series (index = dates, ascending).

    Returns a DataFrame indexed like the input with columns:
      rsi2, down_streak, up_streak, long_sig, short_sig, sig (+1/0/-1)

    sig on day D means: trade the NEXT session. Shorts are 0 unless
    rules.enable_shorts is True; long takes precedence if both fire
    (possible only with degenerate thresholds -- flagged, not hidden).
    """
    r = rsi2(daily_close, rules.rsi_period)
    ch = daily_close.diff()
    down = ch.lt(0)
    up = ch.gt(0)

    def streak(mask: pd.Series) -> pd.Series:
        s = mask.astype(int)
        out = s.copy()
        for i in range(1, len(s)):
            out.iloc[i] = s.iloc[i] * (out.iloc[i - 1] + 1) if s.iloc[i] else 0
        return out

    dstreak, ustreak = streak(down), streak(up)
    long_sig = (r < rules.rsi_long_below) | (dstreak >= rules.consec_down_days)
    short_sig = ((r > rules.rsi_short_above) | (ustreak >= rules.consec_up_days)) \
        if rules.enable_shorts else pd.Series(False, index=daily_close.index)

    sig = pd.Series(0, index=daily_close.index)
    sig = sig.mask(short_sig, -1).mask(long_sig, 1)   # long wins a tie, on record
    return pd.DataFrame({"rsi2": r, "down_streak": dstreak, "up_streak": ustreak,
                         "long_sig": long_sig, "short_sig": short_sig, "sig": sig})


def latest_signal(daily_close: pd.Series, rules: LiveRules) -> dict:
    """The last row of daily_signal as a plain dict -- what signal_check prints."""
    row = daily_signal(daily_close, rules).iloc[-1]
    return {"rsi2": float(row["rsi2"]),
            "down_streak": int(row["down_streak"]),
            "up_streak": int(row["up_streak"]),
            "long_sig": bool(row["long_sig"]),
            "short_sig": bool(row["short_sig"]),
            "sig": int(row["sig"])}
