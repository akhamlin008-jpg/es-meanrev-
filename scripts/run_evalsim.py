"""Turn 'I'm concerned it won't pass' into a number.

Reads daily_pnl.csv (built by scripts/log_trade.py from REAL trades) and runs
the quantlab.evalsim Monte Carlo against the Tradeify rules in config:
P(pass), P(fail), median days to pass, expected attempts, $ per funded account.

Run:   python scripts/run_evalsim.py [config/default.yaml]

Refuses below 15 traded days -- by design. Bootstrapping 6 days of P&L gives
a confident-looking number that means nothing; the gate is the feature.

Interpretation notes printed with the result, because the number alone lies:
- The bootstrap assumes future days resemble logged days (iid resampling).
  Regime changes, sizing changes, or rule changes break that assumption.
- The intraday-excursion proxy in evalsim (1.25x day loss) is crude and
  stated as such in that module. It biases P(pass) DOWN slightly (conservative).
- 15 days is the floor, not sufficiency. The result sharpens as the log grows;
  re-run it every week and watch the number stabilize.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, ".")
from quantlab import evalsim
from quantlab.account import RuleSet

DAILY = Path("daily_pnl.csv")


def main() -> None:
    cfg = yaml.safe_load(open(sys.argv[1] if len(sys.argv) > 1 else "config/default.yaml"))
    if not DAILY.exists():
        print("No daily_pnl.csv yet. Log trades with scripts/log_trade.py first.\n"
              "Traded days on record: 0 of 15 required.")
        return
    daily = pd.read_csv(DAILY)
    pnls = daily["pnl"].astype(float).tolist()
    print(f"Traded days on record: {len(pnls)}  "
          f"(total ${sum(pnls):+.2f}, mean ${sum(pnls)/len(pnls):+.2f}/day, "
          f"worst ${min(pnls):+.2f})")
    if len(pnls) < 15:
        print(f"evalsim gate: need >= 15 traded days, have {len(pnls)}. "
              f"{15 - len(pnls)} to go. This gate exists so the Monte Carlo "
              f"isn't run on noise; keep logging.")
        return

    a = cfg["account"]
    instrument = cfg["live"]["instrument"].upper()
    cap = cfg["execution"]["max_contracts"][instrument]
    rules = RuleSet(a["start_balance"], a["profit_target"], a["eod_trailing_dd"],
                    a["daily_loss_limit"], cap, a["min_trading_days"],
                    a["consistency_pct"], a["drawdown_lock_offset"])
    res = evalsim.simulate(pnls, rules, cfg["evalsim"]["n_sims"],
                           seed=cfg["evalsim"]["seed"])
    print("\nEval Monte Carlo (bootstrap of YOUR logged days):")
    print(json.dumps(res, indent=2))
    print(f"$/funded account (at $99 first / $99 reset): "
          f"{evalsim.cost_per_funded(res, 99, 99):.0f}")
    print("\nVerify the fee and rule numbers against tradeify.co before acting; "
          "they are config inputs, not facts this code knows.")


if __name__ == "__main__":
    main()
