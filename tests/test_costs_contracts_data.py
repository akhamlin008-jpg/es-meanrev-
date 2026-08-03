"""Unit tests for quantlab.costs, quantlab.contracts and quantlab.data.
Contract constants are exchange facts; cost math has a closed form; session
labeling has documented boundaries (CME trade-day roll, RTH window)."""
import pandas as pd
import pytest

from quantlab import data as D
from quantlab.contracts import get_spec
from quantlab.costs import CostModel

from .conftest import make_minute_df


# ---------------------------------------------------------------- contracts

def test_contract_specs_are_exchange_constants():
    es, mes = get_spec("ES"), get_spec("MES")
    assert (es.tick_size, es.tick_value) == (0.25, 12.50)
    assert (mes.tick_size, mes.tick_value) == (0.25, 1.25)

def test_get_spec_case_insensitive():
    assert get_spec("mes") is get_spec("MES")


# -------------------------------------------------------------------- costs

def test_costs_scale_linearly_in_contracts():
    cm = CostModel(commission_rt=1.0, slip_ticks_market=2.0, spec=get_spec("MES"))
    assert cm.commission(3) == 3.0
    assert cm.entry_slippage(3) == 2.0 * 1.25 * 3
    assert cm.exit_slippage(3, "market") == cm.exit_slippage(3, "stop") == 7.5
    assert cm.exit_slippage(3, "limit") == 0.0

def test_breakeven_winrate_closed_form():
    cm = CostModel(commission_rt=4.0, slip_ticks_market=1.0, spec=get_spec("ES"))
    stop_ticks, target_r = 12, 0.5
    risk = stop_ticks * 12.50                    # 150
    reward = target_r * risk                     # 75
    c = 4.0 + 2 * 1.0 * 12.50                    # 29
    assert cm.breakeven_winrate(stop_ticks, target_r) == pytest.approx(
        (risk + c) / (risk + reward))

def test_breakeven_winrate_above_naive_when_costs_positive():
    cm = CostModel(commission_rt=4.0, slip_ticks_market=1.0, spec=get_spec("ES"))
    naive = 1.0 / (1.0 + 0.5)                    # risk/(risk+reward), zero cost
    assert cm.breakeven_winrate(12, 0.5) > naive


# --------------------------------------------------------------------- data

def test_trade_day_rolls_at_18_et():
    df = make_minute_df({"2026-02-02": [("17:59", 100, 100, 100, 100),
                                        ("18:00", 100, 100, 100, 100)]})
    assert str(df.loc[0, "trade_day"]) == "2026-02-02"   # 17:59 -> same day
    assert str(df.loc[1, "trade_day"]) == "2026-02-03"   # 18:00 -> next session

def test_rth_window_boundaries():
    df = make_minute_df({"2026-02-02": [("09:29", 1, 1, 1, 1),
                                        ("09:30", 1, 1, 1, 1),
                                        ("15:59", 1, 1, 1, 1),
                                        ("16:00", 1, 1, 1, 1)]})
    assert list(df["is_rth"]) == [False, True, True, False]

def test_audit_counts_constructed_anomalies():
    df = make_minute_df({"2026-02-02": [
        ("10:00", 100, 101, 99, 100),
        ("10:01", 100, 101, 99, 100),
        ("10:02", 109, 111, 108, 110),    # +10% one-minute jump, OHLC-consistent
    ]})
    df.loc[1, "volume"] = 0                                # zero-volume bar
    df.loc[0, "high"] = 98                                 # high < max(o,c,l)
    a = D.audit(df)
    assert a["zero_volume_bars"] == 1
    assert a["invalid_ohlc_bars"] == 1
    assert a["one_min_moves_gt_3pct"] == 1

def test_load_ohlcv_rejects_missing_columns(tmp_path):
    p = tmp_path / "bad.csv"
    pd.DataFrame({"timestamp": ["2026-02-02 10:00"], "close": [1.0]}).to_csv(p, index=False)
    with pytest.raises(ValueError, match="Missing columns"):
        D.load_ohlcv(str(p), "America/New_York")
