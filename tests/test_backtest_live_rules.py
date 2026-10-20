"""Tests for scripts/backtest_live_rules.run -- the executable form of the
live contract. Synthetic minute bars with outcomes known by construction.

The forced-liquidation tests are the regression suite for a real bug: run()
previously never called account.check_equity() intraday, so a trailing-DD
breach that quantlab.engine models on every bar was invisible here -- the
backtest could report a pass on an account that died intraday.
"""
import pandas as pd
import pytest

import backtest_live_rules as blr
from quantlab.account import RuleSet, TradeifyAccount
from quantlab.contracts import get_spec
from quantlab.costs import CostModel
from quantlab.live_strategy import LiveRules

from .conftest import make_minute_df

TICK = 0.25
TV = 1.25          # MES

# Four priming trade days with strictly falling settlement closes. Their only
# bar is at 16:30 ET -- inside the settlement window (<= 17:00) so it defines
# the daily close, but outside the 10:00-15:55 execution window so no trade
# can fill on them. The long trigger is live from day 2 (RSI2 = 0) and the
# 3-down-closes trigger from day 4; only the day-4 signal has a tradeable
# next session in the frames below.
PRIMING = {
    "2026-02-02": [("16:30", 5000, 5000, 5000, 5000)],
    "2026-02-03": [("16:30", 4990, 4990, 4990, 4990)],
    "2026-02-04": [("16:30", 4980, 4980, 4980, 4980)],
    "2026-02-05": [("16:30", 4970, 4970, 4970, 4970)],
}
ENTRY_OPEN = 4975.0
ENTRY_PX = ENTRY_OPEN + 1 * TICK          # long market entry pays 1 tick slip


def costs():
    return CostModel(commission_rt=1.0, slip_ticks_market=1.0, spec=get_spec("MES"))


def account(eod_trailing_dd=2_000.0):
    return TradeifyAccount(RuleSet(start_balance=50_000, profit_target=3_000,
                                   eod_trailing_dd=eod_trailing_dd,
                                   daily_loss_limit=None, max_contracts=40,
                                   min_trading_days=3, consistency_pct=None,
                                   drawdown_lock_offset=100.0))


def run_on(day6_bars, acct):
    df = make_minute_df({**PRIMING, "2026-02-06": day6_bars})
    return blr.run(df, LiveRules(), +1, 1, costs(), acct)


# ---------------------------------------------------------------- fills

def test_time_exit_prices_and_pnl_exact():
    trades = run_on([("09:30", 4970, 4971, 4969, 4970),   # before entry window
                     ("10:00", ENTRY_OPEN, 4976, 4974, 4975),
                     ("12:00", 4975, 4976, 4974, 4975),
                     ("15:55", 4980, 4980, 4980, 4980)], account())
    assert len(trades) == 1
    t = trades.iloc[0]
    assert t["reason"] == "time_exit"
    assert t["entry"] == pytest.approx(ENTRY_PX)
    assert t["exit"] == pytest.approx(4980 - TICK)        # market exit pays slip
    expected = (4980 - TICK - ENTRY_PX) / TICK * TV - 1.0  # gross - commission
    assert t["pnl"] == pytest.approx(expected)

def test_stop_fills_at_stop_minus_slippage():
    stop_px = ENTRY_PX * (1 - 0.02)
    trades = run_on([("10:00", ENTRY_OPEN, 4976, 4974, 4975),
                     ("11:00", 4970, 4971, stop_px - 5, 4960),  # low pierces stop
                     ("15:55", 4980, 4980, 4980, 4980)], account())
    t = trades.iloc[0]
    assert t["reason"] == "stop"
    assert t["exit"] == pytest.approx(stop_px - TICK, abs=0.006)  # CSV rounds 2dp
    assert t["pnl"] < 0

def test_no_trade_when_next_session_has_no_bars_in_window():
    trades = run_on([("16:30", 4970, 4970, 4970, 4970)], account())
    assert trades.empty


# ------------------------------------------- intraday trailing DD (the fix)

# Price path: dips to 4960 at 11:00 (unrealized -$76.25 on 1 MES; never near
# the 2% stop) then recovers to close 4990. With a $50 trailing DD the dip
# kills the account intraday; with the default $2000 it is a routine winner.
DIP_AND_RECOVER = [("10:00", ENTRY_OPEN, 4976, 4974, 4975),
                   ("11:00", 4965, 4966, 4958, 4960),
                   ("13:00", 4970, 4975, 4969, 4975),
                   ("15:55", 4990, 4990, 4990, 4990)]

def test_intraday_dd_breach_forces_liquidation():
    acct = account(eod_trailing_dd=50.0)          # dd line at 49_950
    trades = run_on(DIP_AND_RECOVER, acct)
    assert acct.failed and "intraday" in acct.fail_reason
    assert len(trades) == 1
    t = trades.iloc[0]
    assert t["reason"] == "forced_liquidation_dd"
    assert t["exit"] == pytest.approx(4960 - TICK)  # liquidated at the breach bar
    assert t["note"] == "ACCOUNT FAILED HERE"

def test_same_path_survives_with_normal_dd():
    acct = account(eod_trailing_dd=2_000.0)
    trades = run_on(DIP_AND_RECOVER, acct)
    assert not acct.failed
    assert trades.iloc[0]["reason"] == "time_exit"
    assert trades.iloc[0]["pnl"] > 0

def test_accountless_shadow_run_is_untouched_by_the_check():
    trades = run_on(DIP_AND_RECOVER, None)
    assert trades.iloc[0]["reason"] == "time_exit"

def test_realized_stop_loss_below_dd_line_fails_account():
    # the stop-out realizes about -$500 on 1 MES; with a $400 trailing DD the
    # REALIZED balance lands below the line, which must kill the account even
    # though no later bar ever marks an open position against it.
    stop_px = ENTRY_PX * (1 - 0.02)
    acct = account(eod_trailing_dd=400.0)
    trades = run_on([("10:00", ENTRY_OPEN, 4976, 4974, 4975),
                     ("11:00", 4970, 4971, stop_px - 5, 4960),
                     ("15:55", 4990, 4990, 4990, 4990)], acct)
    assert acct.failed
    assert trades.iloc[0]["reason"] == "stop"
    assert trades.iloc[0]["note"] == "ACCOUNT FAILED HERE"

def test_stop_beats_equity_check_within_one_bar():
    # the crash bar both pierces the stop and breaches equity: stop first
    # (worst case) is the documented fill discipline.
    stop_px = ENTRY_PX * (1 - 0.02)
    acct = account(eod_trailing_dd=50.0)
    trades = run_on([("10:00", ENTRY_OPEN, 4976, 4974, 4975),
                     ("11:00", 4900, 4901, stop_px - 5, 4870),
                     ("15:55", 4990, 4990, 4990, 4990)], acct)
    assert trades.iloc[0]["reason"] == "stop"


# ---------------------------------------------------------------- helpers

def test_daily_closes_use_settlement_window():
    df = make_minute_df({"2026-02-02": [("16:59", 100, 100, 100, 100),
                                        ("17:01", 200, 200, 200, 200)]})
    closes = blr.daily_closes_from_minutes(df)
    # 17:01 belongs to the same trade day but is past the settlement cutoff
    assert closes.iloc[0] == 100.0
