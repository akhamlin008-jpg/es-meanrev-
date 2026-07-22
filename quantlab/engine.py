"""Event-driven bar engine. Fill discipline (all conservative, all documented):
- Entries: market at NEXT bar open +/- slippage (no lookahead).
- Stops: filled at stop price +/- slippage if bar range touches it.
- Targets: limit fills require TRADE-THROUGH (bar must exceed the limit), no slippage.
- Stop and target both inside one bar -> assume STOP FIRST (worst case).
- Flatten at configured time; no entries after cutoff; DLL soft-breach flattens."""
from dataclasses import dataclass

import pandas as pd

from .account import TradeifyAccount
from .costs import CostModel
from .sizing import SizingContext, SizingScheme


@dataclass
class Trade:
    entry_time: object
    exit_time: object
    side: int
    contracts: int
    entry_px: float
    exit_px: float
    pnl: float
    exit_reason: str
    session_block: str
    hold_seconds: float


def run_backtest(df: pd.DataFrame, signals: pd.Series, account: TradeifyAccount,
                 sizer: SizingScheme, costs: CostModel, geom: dict, sess: dict,
                 max_contracts: int):
    spec = costs.spec
    tick, tv = spec.tick_size, spec.tick_value
    stop_ticks, target_r = geom["stop_ticks"], geom["target_r"]
    time_stop = geom["time_stop_bars"]
    flat_t = _hm(sess["flatten_time"])
    no_new_t = _hm(sess["no_new_entries_after"])
    rth_only = sess.get("rth_only", True)

    trades, sizing_log = [], []
    pos = None
    cur_day, traded_today = None, False
    o, h, l, c = (df[k].values for k in ("open", "high", "low", "close"))
    ts = df["timestamp"]
    blocks = df["session_block"].values
    tdays = df["trade_day"].values
    rth = df["is_rth"].values
    sig = signals.values

    for i in range(1, len(df)):
        if account.failed:
            break
        day = tdays[i]
        if cur_day is None:
            cur_day = day
        if day != cur_day:                       # 17:00 ET rollover happened
            account.end_of_day(traded_today)
            cur_day, traded_today = day, False
            if account.passed:
                break
        t = ts.iloc[i]
        hm = t.hour * 60 + t.minute

        # --- manage open position ---
        if pos is not None:
            side, n, entry_px, stop_px, tgt_px, ei = pos
            exit_px = exit_reason = None
            if side == 1:
                if l[i] <= stop_px:
                    exit_px, exit_reason = stop_px - costs.slip_ticks_market * tick, "stop"
                elif h[i] > tgt_px:
                    exit_px, exit_reason = tgt_px, "target"
            else:
                if h[i] >= stop_px:
                    exit_px, exit_reason = stop_px + costs.slip_ticks_market * tick, "stop"
                elif l[i] < tgt_px:
                    exit_px, exit_reason = tgt_px, "target"
            if exit_px is None and (i - ei) >= time_stop:
                exit_px, exit_reason = c[i], "time"
            if exit_px is None and (hm >= flat_t or account.locked_today):
                exit_px, exit_reason = c[i], "flatten"
            if exit_px is not None:
                gross = side * (exit_px - entry_px) / tick * tv * n
                pnl = gross - costs.commission(n)
                account.on_realized(pnl)
                trades.append(Trade(ts.iloc[ei], t, side, n, entry_px, exit_px, pnl,
                                    exit_reason, blocks[ei],
                                    (t - ts.iloc[ei]).total_seconds()))
                pos = None
            else:
                unreal = side * (c[i] - entry_px) / tick * tv * n
                account.check_equity(account.balance + unreal)
                if account.failed:
                    break

        # --- entries (signal on bar i-1 fills at open of bar i) ---
        if pos is None and sig[i - 1] != 0 and account.can_enter() and hm < no_new_t \
                and (rth[i] or not rth_only):
            side = int(sig[i - 1])
            ctx = SizingContext(account.balance, account.rules.start_balance,
                                account.hwm_eod, account.dd_limit, stop_ticks, tv)
            n = min(sizer.contracts(ctx), max_contracts)
            # Reduce size only if a full stop-out would STRICTLY breach the DD line
            # (land below it). A stop-out landing at-or-above the line is a normal
            # losing trade and is allowed -- otherwise the account freezes when
            # behind and can never recover.
            while n > 1 and account.balance - (stop_ticks * tv * n
                    + costs.commission(n) + costs.entry_slippage(n)) < account.dd_limit:
                n -= 1
            sizing_log.append({**sizer.log_row(ctx, n), "time": str(ts.iloc[i])})
            if n > 0:
                entry_px = o[i] + side * costs.slip_ticks_market * tick
                stop_px = entry_px - side * stop_ticks * tick
                tgt_px = entry_px + side * stop_ticks * tick * target_r
                pos = (side, n, entry_px, stop_px, tgt_px, i)
                traded_today = True

    account.end_of_day(traded_today)
    return trades, sizing_log, account


def _hm(s: str) -> int:
    hh, mm = s.split(":")
    return int(hh) * 60 + int(mm)
