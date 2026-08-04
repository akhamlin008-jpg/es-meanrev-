"""Shared fixtures. Everything here is synthetic and offline: tests must be
runnable on a clean machine with runtime deps only (numpy, pandas, pyyaml).

The minute-bar builder goes through quantlab.data.label_sessions so tests
exercise the same session labeling the real loaders produce.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from quantlab import data as D               # noqa: E402
from quantlab.contracts import get_spec      # noqa: E402
from quantlab.costs import CostModel         # noqa: E402
from quantlab.live_strategy import LiveRules  # noqa: E402

TZ = "America/New_York"


def make_minute_df(day_bars: dict) -> pd.DataFrame:
    """Build a labeled minute-bar frame from {date_str: [(hh:mm, o, h, l, c), ...]}.

    Timestamps are ET (tz-aware). Volume is a constant positive number so the
    data audit stays clean unless a test corrupts it on purpose.
    """
    rows = []
    for day, bars in sorted(day_bars.items()):
        for t, o, h, l, c in bars:
            rows.append({"timestamp": pd.Timestamp(f"{day} {t}", tz=TZ),
                         "open": float(o), "high": float(h),
                         "low": float(l), "close": float(c),
                         "volume": 100})
    df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    return D.label_sessions(df)


def flat_day(px: float) -> list:
    """A do-nothing session: one pre-entry bar, the 10:00 entry bar, a midday
    bar and the 15:55 flatten bar, all at the same price."""
    return [("09:30", px, px, px, px),
            ("10:00", px, px, px, px),
            ("12:00", px, px, px, px),
            ("15:55", px, px, px, px)]


def signal_priming_days(start: str, n_down: int, top: float, step: float) -> dict:
    """n_down+1 trade days of strictly falling settlement closes so the live
    long trigger (>= 3 consecutive down closes, and an RSI2 pinned near 0)
    fires on the last of them. Each day is a flat session at its close."""
    days = pd.bdate_range(start, periods=n_down + 1)
    out = {}
    px = top
    for d in days:
        out[d.strftime("%Y-%m-%d")] = flat_day(px)
        px -= step
    return out


@pytest.fixture
def rules() -> LiveRules:
    return LiveRules()          # defaults mirror config/default.yaml


@pytest.fixture
def mes_costs() -> CostModel:
    # config/default.yaml: commission_rt_mes-style number, 1 tick market slippage
    return CostModel(commission_rt=1.0, slip_ticks_market=1.0, spec=get_spec("MES"))
