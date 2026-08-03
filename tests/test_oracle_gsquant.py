"""Validation oracles: our hand-rolled math checked against independent
implementations (gs-quant timeseries, scipy). DEV/CI ONLY -- gs-quant and
scipy are never runtime dependencies (tests/test_import_guard.py enforces
that). Run with:  pytest -m oracle

Convention reconciliation, on the record:
- rsi2 uses Wilder smoothing via ewm(alpha=1/period, adjust=False), seeded on
  the first observation. gs-quant's relative_strength_index uses Wilder's
  smoothed moving average seeded with a plain SMA of the first `period`
  values. The two recursions are identical after the seed, so they converge
  geometrically: on 2-period RSI the difference is < 1e-9 within 50 bars.
  We assert tail agreement, not warmup agreement.
"""
import numpy as np
import pandas as pd
import pytest

from quantlab.live_strategy import rsi2

gs_ts = pytest.importorskip(
    "gs_quant.timeseries", reason="oracle tests need requirements-dev.txt")

pytestmark = pytest.mark.oracle

WARMUP = 50


def _gbm(seed, n=400, s0=5000.0, drift=0.0001, vol=0.01):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-01", periods=n)
    return pd.Series(s0 * np.exp(np.cumsum(rng.normal(drift, vol, n))), index=idx)


@pytest.mark.parametrize("seed", [7, 42, 2026])
def test_rsi2_matches_gs_quant_after_seed_convergence(seed):
    px = _gbm(seed)
    ours = rsi2(px, 2)
    gs = gs_ts.relative_strength_index(px, 2)
    both = pd.concat([ours, gs], axis=1, keys=["ours", "gs"]).dropna()
    tail = (both["ours"] - both["gs"]).abs().iloc[WARMUP:]
    assert tail.max() < 1e-9

def test_rsi2_matches_gs_quant_at_live_period_14_too():
    # guard against the reconciliation silently depending on period=2
    px = _gbm(11)
    ours = rsi2(px, 14)
    gs = gs_ts.relative_strength_index(px, 14)
    both = pd.concat([ours, gs], axis=1, keys=["ours", "gs"]).dropna()
    # seed convergence is geometric at rate (1 - 1/period): slower at 14 than
    # at 2, so measure the last 50 bars of the 400-bar series
    assert (both["ours"] - both["gs"]).abs().iloc[-50:].max() < 1e-8
