import json
import sys

import yaml

sys.path.insert(0, ".")
from quantlab import data as D
from quantlab import evalsim
from quantlab.account import RuleSet, TradeifyAccount, hft_rule_report
from quantlab.contracts import get_spec
from quantlab.costs import CostModel
from quantlab.engine import run_backtest
from quantlab.report import summarize, trades_frame
from quantlab.sizing import build_sizer
from quantlab.strategies import REGISTRY

cfg = yaml.safe_load(open(sys.argv[1] if len(sys.argv) > 1 else "config/default.yaml"))
dcfg = cfg["data"]
df = D.load_ohlcv(dcfg["path"], dcfg["tz"], dcfg.get("naive_stamps_are", "America/New_York"))
print("DATA AUDIT (fix problems before believing anything below):")
print(json.dumps(D.audit(df), indent=2))

spec = get_spec(dcfg["symbol"])
comm = cfg["costs"]["commission_rt_es"] if spec.symbol == "ES" else cfg["costs"]["commission_rt_mes"]
costs = CostModel(comm, cfg["costs"]["slippage_ticks_market"], spec)
a = cfg["account"]
max_contracts = cfg["execution"]["max_contracts"][spec.symbol]
rules = RuleSet(a["start_balance"], a["profit_target"], a["eod_trailing_dd"],
                a["daily_loss_limit"], max_contracts, a["min_trading_days"],
                a["consistency_pct"], a["drawdown_lock_offset"])
account = TradeifyAccount(rules)
sname = cfg["strategy"]["name"]
signals = REGISTRY[sname](df, cfg["strategy"][sname])
trades, slog, account = run_backtest(df, signals, account, build_sizer(cfg["sizing"]),
                                     costs, cfg["trade_geometry"], cfg["session"],
                                     max_contracts)
print("\n" + summarize(trades, account, costs, cfg["trade_geometry"]))
print("\nAnti-HFT rule:", hft_rule_report(trades))
trades_frame(trades).to_csv("trades_out.csv", index=False)
json.dump(slog, open("sizing_log.json", "w"), indent=1)
if len(account.daily_pnls) >= 15:
    res = evalsim.simulate(account.daily_pnls, rules, cfg["evalsim"]["n_sims"],
                           seed=cfg["evalsim"]["seed"])
    print("\nEval Monte Carlo:", json.dumps(res, indent=2))
    print(f"$/funded (this rule set): {evalsim.cost_per_funded(res, 99, 99):.0f}")
else:
    print("\nEval Monte Carlo skipped: fewer than 15 trading days of history.")
