"""Unit tests for quantlab.live_strategy -- the single source of truth for the
live rules. Closed-form or construction-guaranteed answers only."""
import numpy as np
import pandas as pd
import pytest

from quantlab.live_strategy import LiveRules, daily_signal, latest_signal, rsi2


def _series(vals):
    idx = pd.bdate_range("2026-01-05", periods=len(vals))
    return pd.Series([float(v) for v in vals], index=idx)


# ------------------------------------------------------------------- rsi2

def test_rsi2_bounded_0_100():
    rng = np.random.default_rng(3)
    px = _series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300))))
    r = rsi2(px).dropna()
    assert (r >= 0).all() and (r <= 100).all()

def test_rsi2_pinned_at_100_on_monotone_rise():
    r = rsi2(_series([100, 101, 102, 103, 104, 105]))
    # no down moves -> avg loss 0 -> RSI = 100 exactly
    assert r.iloc[-1] == pytest.approx(100.0)

def test_rsi2_pinned_at_0_on_monotone_fall():
    r = rsi2(_series([105, 104, 103, 102, 101, 100]))
    assert r.iloc[-1] == pytest.approx(0.0)

def test_rsi2_wilder_smoothing_two_step_closed_form():
    # closes 100, 101, 100: gains (1, 0), losses (0, 1), alpha = 1/2
    #   up_2 = 0.5*1 + 0.5*0 = 0.5 ; dn_2 = 0.5*0 + 0.5*1 = 0.5
    # RSI = 100 - 100/(1 + 1) = 50
    r = rsi2(_series([100, 101, 100]))
    assert r.iloc[-1] == pytest.approx(50.0)


# ------------------------------------------------------------- daily_signal

def test_down_streak_counts_consecutive_down_closes():
    sig = daily_signal(_series([100, 99, 98, 97, 98, 97]), LiveRules())
    assert list(sig["down_streak"]) == [0, 1, 2, 3, 0, 1]

def test_long_fires_on_three_down_closes():
    sig = daily_signal(_series([100, 99, 98, 97]), LiveRules())
    assert bool(sig["long_sig"].iloc[-1]) and sig["sig"].iloc[-1] == 1

def test_long_fires_on_rsi_alone_without_streak():
    # big drop, small up day, big drop: streak never reaches 3 but RSI2 stays
    # deep in oversold on the final bar.
    px = _series([100, 90, 90.5, 82])
    rules = LiveRules()
    sig = daily_signal(px, rules)
    last = sig.iloc[-1]
    assert last["down_streak"] < rules.consec_down_days
    assert last["rsi2"] < rules.rsi_long_below
    assert last["sig"] == 1

def test_shorts_disabled_by_default():
    px = _series([100, 101, 102, 103, 104])       # 4 straight up closes
    sig = daily_signal(px, LiveRules())
    assert not sig["short_sig"].any()
    assert (sig["sig"] >= 0).all()

def test_shorts_fire_when_enabled():
    px = _series([100, 101, 102, 103, 104])
    sig = daily_signal(px, LiveRules(enable_shorts=True))
    assert sig["sig"].iloc[-1] == -1

def test_long_precedence_on_degenerate_thresholds():
    # thresholds that make both sides fire at once: long must win, on record
    rules = LiveRules(rsi_long_below=101.0, rsi_short_above=-1.0,
                      enable_shorts=True)
    sig = daily_signal(_series([100, 100.5, 100.2, 100.7]), rules)
    both = sig["long_sig"] & sig["short_sig"]
    assert both.any()
    assert (sig.loc[both, "sig"] == 1).all()

def test_latest_signal_types_and_agreement():
    px = _series([100, 99, 98, 97])
    d = latest_signal(px, LiveRules())
    assert isinstance(d["sig"], int) and isinstance(d["rsi2"], float)
    assert d["sig"] == int(daily_signal(px, LiveRules())["sig"].iloc[-1])
