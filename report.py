from collections import defaultdict

import numpy as np
import pandas as pd


def summarize(trades, account, costs, geom) -> str:
    lines = []
    be = costs.breakeven_winrate(geom["stop_ticks"], geom["target_r"])
    if not trades:
        return "No trades generated. Check signal params / session filters."
    pnl = np.array([t.pnl for t in trades])
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    wr = len(wins) / len(pnl)
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    eq = np.cumsum(pnl)
    dd = (np.maximum.accumulate(eq) - eq).max()
    lines += [
        f"Trades: {len(pnl)}   Net PnL: ${pnl.sum():,.2f}   Expectancy/trade: ${pnl.mean():,.2f}",
        f"Win rate: {wr:.1%}   REQUIRED breakeven WR at this geometry+costs: {be:.1%}   "
        f"{'MEETS' if wr > be else '** FAILS **'} the cost-adjusted bar",
        f"Profit factor: {pf:.2f}   MaxDD (trade equity): ${dd:,.2f}",
        f"Account: passed={account.passed} failed={account.failed} {account.fail_reason}",
        f"Trading days: {account.trading_days}   Final balance: ${account.balance:,.2f}",
    ]
    if account.daily_pnls:
        dp = np.array(account.daily_pnls)
        tot = dp.sum()
        if tot > 0:
            lines.append(f"Best-day share of profit: {dp.max() / tot:.1%} "
                         f"(Select eval needs <=40%, Growth funded <=35%)")
    by = defaultdict(list)
    for t in trades:
        by[t.session_block].append(t.pnl)
    lines.append("\nPer-session expectancy (edge lives or dies here):")
    for k in sorted(by):
        a = np.array(by[k])
        lines.append(f"  {k:18s} n={len(a):4d}  mean=${a.mean():8.2f}  total=${a.sum():10.2f}")
    return "\n".join(lines)


def trades_frame(trades) -> pd.DataFrame:
    return pd.DataFrame([vars(t) for t in trades])
