"""Monte Carlo of the eval option. Bootstraps DAILY PnL (whole-day resampling,
because trade-level bootstrap destroys intraday sequence effects) and simulates
a rule set to estimate P(pass), expected attempts, and $ per funded account.

KNOWN LIMITATION (stated, not hidden): the intraday-excursion proxy below
(1.25x the day's realized loss) is crude. It will be replaced with true
intraday equity paths exported by the engine once real data is flowing."""
import numpy as np


def simulate(daily_pnls, rules, n_sims=20000, max_days=60, seed=7):
    if len(daily_pnls) < 15:
        raise ValueError("Need >=15 real trading days of PnL before this is meaningful.")
    rng = np.random.default_rng(seed)
    days = np.asarray(daily_pnls, float)
    passes = fails = 0
    days_to_pass = []
    for _ in range(n_sims):
        bal = rules.start_balance
        hwm = bal
        dd_lim = bal - rules.eod_trailing_dd
        dps, ok = [], None
        for d in range(max_days):
            p = float(rng.choice(days))
            if rules.daily_loss_limit is not None:
                p = max(p, -rules.daily_loss_limit)          # soft-breach truncation
            intraday_low = bal + min(p, 0) * 1.25            # crude excursion proxy
            if intraday_low <= dd_lim or bal + p <= dd_lim:
                ok = False
                break
            bal += p
            dps.append(p)
            if bal > hwm:
                hwm = bal
                dd_lim = min(max(dd_lim, hwm - rules.eod_trailing_dd),
                             rules.start_balance + rules.drawdown_lock_offset)
            profit = bal - rules.start_balance
            if profit >= rules.profit_target and (d + 1) >= rules.min_trading_days:
                if rules.consistency_pct is None or \
                        max(dps) / profit <= rules.consistency_pct:
                    ok = True
                    days_to_pass.append(d + 1)
                    break
        if ok is True:
            passes += 1
        elif ok is False:
            fails += 1
    p_pass = passes / n_sims
    return {"p_pass": p_pass,
            "p_fail": fails / n_sims,
            "p_timeout_60d": 1 - (passes + fails) / n_sims,
            "median_days_to_pass": float(np.median(days_to_pass)) if days_to_pass else None,
            "expected_attempts": (1 / p_pass) if p_pass > 0 else float("inf")}


def cost_per_funded(res, first_fee, reset_fee):
    if res["p_pass"] == 0:
        return float("inf")
    return first_fee + (res["expected_attempts"] - 1) * reset_fee
