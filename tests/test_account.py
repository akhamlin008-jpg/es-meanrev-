"""Unit tests for the Tradeify rule simulator (quantlab.account).
Every rule is checked against a scenario whose outcome is known by
construction: intraday trailing DD, EOD trail + lock, daily loss lock,
consistency gate, and the anti-HFT profit rule."""
from types import SimpleNamespace

from quantlab.account import RuleSet, TradeifyAccount, hft_rule_report


def make_account(**over):
    base = dict(start_balance=50_000, profit_target=3_000, eod_trailing_dd=2_000,
                daily_loss_limit=None, max_contracts=40, min_trading_days=3,
                consistency_pct=None, drawdown_lock_offset=100.0)
    base.update(over)
    return TradeifyAccount(RuleSet(**base))


# ------------------------------------------------- intraday trailing DD

def test_check_equity_breach_is_inclusive():
    a = make_account()
    a.check_equity(48_000.0)          # exactly at the line: breached (<=)
    assert a.failed and "intraday" in a.fail_reason

def test_check_equity_above_line_survives():
    a = make_account()
    a.check_equity(48_000.01)
    assert not a.failed

def test_failed_account_cannot_enter():
    a = make_account()
    a.check_equity(0.0)
    assert not a.can_enter()


# ------------------------------------------------- EOD trail and lock

def test_dd_limit_trails_eod_high_water_mark():
    a = make_account()
    a.on_realized(+500.0)
    a.end_of_day(True)
    assert a.hwm_eod == 50_500.0
    assert a.dd_limit == 48_500.0     # hwm - 2000, below the 50_100 lock

def test_dd_limit_locks_at_start_plus_offset():
    a = make_account()
    a.on_realized(+5_000.0)
    a.end_of_day(True)
    # trail would be 53_000; the lock caps it at start + offset = 50_100
    assert a.dd_limit == 50_100.0

def test_dd_limit_never_moves_down():
    a = make_account()
    a.on_realized(+500.0)
    a.end_of_day(True)
    a.on_realized(-800.0)
    a.end_of_day(True)
    assert a.dd_limit == 48_500.0     # a losing day cannot relax the line


# ------------------------------------------------- daily loss limit

def test_daily_loss_limit_soft_breach_locks_day_only():
    a = make_account(daily_loss_limit=500.0)
    a.on_realized(-600.0)
    assert a.locked_today and not a.failed and not a.can_enter()
    a.end_of_day(True)
    assert not a.locked_today and a.can_enter()


# ------------------------------------------------- pass logic

def test_pass_requires_min_trading_days():
    a = make_account()
    a.on_realized(+4_000.0)
    a.end_of_day(True)                # profit target hit on day 1 of 3
    assert not a.passed

def test_pass_with_consistent_days():
    a = make_account(consistency_pct=0.4)
    for _ in range(3):
        a.on_realized(+1_500.0)
        a.end_of_day(True)
    # profit 4500, best day 1500/4500 = 0.33 <= 0.4 -> pass
    assert a.passed

def test_consistency_blocks_single_big_day():
    a = make_account(consistency_pct=0.4)
    for pnl in (+3_000.0, +100.0, +100.0):
        a.on_realized(pnl)
        a.end_of_day(True)
    # profit 3200, best day 3000/3200 = 0.94 > 0.4 -> target hit but no pass
    assert not a.passed


# ------------------------------------------------- anti-HFT rule

def _trade(pnl, hold_seconds):
    return SimpleNamespace(pnl=pnl, hold_seconds=hold_seconds)

def test_hft_rule_compliant_on_minute_bars():
    trades = [_trade(100.0, 60), _trade(-50.0, 120), _trade(80.0, 300)]
    rep = hft_rule_report(trades)
    assert rep["compliant"] is True

def test_hft_rule_flags_fast_profit():
    # 2 of 3 trades and all of the profit come from sub-10s holds
    trades = [_trade(500.0, 5), _trade(400.0, 8), _trade(-100.0, 60)]
    rep = hft_rule_report(trades)
    assert rep["compliant"] is False

def test_hft_rule_empty_trades():
    assert hft_rule_report([])["compliant"] is None
