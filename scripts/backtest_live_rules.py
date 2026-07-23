"""Backtest THE EXACT LIVE RULES on the committed 1-min ES data.

This is the reconciliation: the signal comes from quantlab.live_strategy
(the same module signal_check.py runs every night), and execution follows the
same written contract (config `live:` block): enter at the 10:00 ET bar open
next session, hard stop at stop_pct, flatten at exit_time. Costs, Tradeify
account rules, and per-instrument contract caps all apply.

Run:   python scripts/backtest_live_rules.py [config/default.yaml]

Honest limitations, on the record:
- Daily closes here are derived from the 1-min file (last bar at/before 17:00
  ET per trade day). The live signal uses Yahoo ES=F daily closes, which
  settle at the same time but can differ by a tick or two. Small, but real.
- ~74 trade days of data means a daily-frequency strategy fires only a
  handful of times. Treat every statistic below as machinery verification
  and a small-sample estimate, NOT proof of edge. The SPY long-history
  validation (validate_spy.py) is where statistical power lives.
- Longs and shorts are reported SEPARATELY. Even when enable_shorts is false
  in config, this script also runs a shadow short backtest (clearly labeled
  SHADOW / NOT LIVE) so the short side accumulates evidence before it is
  ever enabled.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, ".")
from quantlab import data as D
from quantlab.account import RuleSet, TradeifyAccount
from quantlab.contracts import get_spec
from quantlab.costs import CostModel
from quantlab.live_strategy import LiveRules, daily_signal


def _hm(s: str) -> int:
    hh, mm = s.split(":")
    return int(hh) * 60 + int(mm)


def daily_closes_from_minutes(df: pd.DataFrame) -> pd.Series:
    """Settlement-proxy close per trade day: last bar at/before 17:00 ET."""
    hm = df["timestamp"].dt.hour * 60 + df["timestamp"].dt.minute
    sub = df[hm <= 17 * 60]
    return sub.groupby("trade_day")["close"].last()


def run(df: pd.DataFrame, rules: LiveRules, side_filter: int, contracts: int,
        costs: CostModel, account: TradeifyAccount | None):
    """Execute the live rules bar-by-bar. side_filter: +1 longs only, -1 shorts only.
    Fill discipline matches quantlab.engine: market entries/stops pay slippage;
    if stop and exit conflict within a bar, assume the stop (worst case)."""
    tick, tv = costs.spec.tick_size, costs.spec.tick_value
    closes = daily_closes_from_minutes(df)
    sig = daily_signal(closes, rules)["sig"]
    entry_hm, exit_hm = _hm(rules.entry_time), _hm(rules.exit_time)

    days = sorted(df["trade_day"].unique())
    by_day = dict(tuple(df.groupby("trade_day")))
    trades = []
    for prev, day in zip(days, days[1:]):
        if prev not in sig.index or sig.loc[prev] == 0 or sig.loc[prev] != side_filter:
            continue
        side = int(sig.loc[prev])
        bars = by_day[day]
        hm = bars["timestamp"].dt.hour * 60 + bars["timestamp"].dt.minute
        session = bars[(hm >= entry_hm) & (hm <= exit_hm)]
        if session.empty:
            continue
        e = session.iloc[0]
        entry_px = float(e["open"]) + side * costs.slip_ticks_market * tick
        stop_px = entry_px * (1 - side * rules.stop_pct)
        exit_px, exit_reason, exit_t = None, None, None
        for _, b in session.iterrows():
            hit = (b["low"] <= stop_px) if side == 1 else (b["high"] >= stop_px)
            if hit:
                exit_px = stop_px - side * costs.slip_ticks_market * tick
                exit_reason, exit_t = "stop", b["timestamp"]
                break
        if exit_px is None:
            last = session.iloc[-1]
            exit_px = float(last["close"]) - side * costs.slip_ticks_market * tick
            exit_reason, exit_t = "time_exit", last["timestamp"]
        gross = side * (exit_px - entry_px) / tick * tv * contracts
        pnl = gross - costs.commission(contracts)
        if account is not None:
            account.on_realized(pnl)
            account.end_of_day(True)
            if account.failed:
                trades.append({"trade_day": str(day), "side": side, "contracts": contracts,
                               "entry": entry_px, "exit": exit_px, "reason": exit_reason,
                               "pnl": round(pnl, 2), "note": "ACCOUNT FAILED HERE"})
                break
        trades.append({"trade_day": str(day), "side": side, "contracts": contracts,
                       "entry": round(entry_px, 2), "exit": round(exit_px, 2),
                       "reason": exit_reason, "pnl": round(pnl, 2),
                       "exit_time": str(exit_t)})
    return pd.DataFrame(trades)


def describe(label: str, t: pd.DataFrame) -> str:
    if t.empty:
        return f"{label}: 0 trades in this sample."
    p = t["pnl"]
    tstat = (p.mean() / (p.std(ddof=1) / np.sqrt(len(p)))) if len(p) > 1 and p.std(ddof=1) > 0 else float("nan")
    return (f"{label}: n={len(p)}  total=${p.sum():+.2f}  mean=${p.mean():+.2f}/trade  "
            f"win={(p > 0).mean():.0%}  worst=${p.min():+.2f}  t={tstat:+.2f}"
            + ("  [n too small for inference]" if len(p) < 20 else ""))


def main() -> None:
    cfg = yaml.safe_load(open(sys.argv[1] if len(sys.argv) > 1 else "config/default.yaml"))
    rules = LiveRules.from_config(cfg)
    dcfg = cfg["data"]
    df = D.load_ohlcv(dcfg["path"], dcfg["tz"], dcfg.get("naive_stamps_are", "America/New_York"))
    print("DATA AUDIT:", json.dumps(D.audit(df)))
    print("LIVE RULES UNDER TEST:", json.dumps(asdict(rules)), "\n")

    spec = get_spec(rules.instrument)
    comm = cfg["costs"]["commission_rt_es"] if spec.symbol == "ES" else cfg["costs"]["commission_rt_mes"]
    costs = CostModel(comm, cfg["costs"]["slippage_ticks_market"], spec)
    cap = cfg["execution"]["max_contracts"][spec.symbol]
    n = min(cfg["sizing"].get("fixed", {}).get("contracts", 1), cap)
    print(f"Instrument {spec.symbol}: {n} contract(s) per trade (cap {cap}). "
          f"Fixed size on purpose -- judge the signal before sizing it.\n")

    a = cfg["account"]
    acct = TradeifyAccount(RuleSet(a["start_balance"], a["profit_target"],
                                   a["eod_trailing_dd"], a["daily_loss_limit"], cap,
                                   a["min_trading_days"], a["consistency_pct"],
                                   a["drawdown_lock_offset"]))
    longs = run(df, rules, +1, n, costs, acct)
    print(describe("LONG  (live rules)", longs))

    # Shadow short backtest: mirrored triggers, forced on, separate account-less run.
    shadow = LiveRules(**{**asdict(rules), "enable_shorts": True})
    shorts = run(df, shadow, -1, n, costs, None)
    tag = "LIVE" if rules.enable_shorts else "SHADOW -- NOT LIVE, evidence only"
    print(describe(f"SHORT ({tag})", shorts))
    print("\nShorts stay disabled until they clear validate_spy.py (drift-adjusted) "
          "AND show acceptable results here. Upward drift means the short side "
          "must earn its way in; it does not inherit the long side's evidence.")

    longs.to_csv("backtest_live_long.csv", index=False)
    shorts.to_csv("backtest_live_short_shadow.csv", index=False)
    print("\nWrote backtest_live_long.csv, backtest_live_short_shadow.csv")
    if acct.failed:
        print(f"ACCOUNT STATUS: FAILED -- {acct.fail_reason}")
    else:
        print(f"ACCOUNT STATUS: ok  balance=${acct.balance:,.2f}  "
              f"days={acct.trading_days}  passed={acct.passed}")


if __name__ == "__main__":
    main()
