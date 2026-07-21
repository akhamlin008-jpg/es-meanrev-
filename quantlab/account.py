"""Tradeify rule simulator. Encodes: EOD trailing drawdown (updates at session
close, enforced in REAL TIME intraday), optional daily loss limit (soft breach:
flatten + lock for the day, account survives), consistency tracking, minimum
trading days, drawdown lock, and the >10s / >50% anti-HFT profit rule.

VERIFY all parameter values against tradeify.co before spending money --
they are config inputs, not facts baked into this code."""
from dataclasses import dataclass, field


@dataclass
class RuleSet:
    start_balance: float
    profit_target: float
    eod_trailing_dd: float
    daily_loss_limit: float | None
    max_contracts: int
    min_trading_days: int
    consistency_pct: float | None
    drawdown_lock_offset: float = 100.0


@dataclass
class TradeifyAccount:
    rules: RuleSet
    balance: float = field(init=False)
    dd_limit: float = field(init=False)
    hwm_eod: float = field(init=False)
    day_realized: float = 0.0
    locked_today: bool = False
    failed: bool = False
    passed: bool = False
    fail_reason: str = ""
    daily_pnls: list = field(default_factory=list)
    trading_days: int = 0

    def __post_init__(self):
        self.balance = self.rules.start_balance
        self.hwm_eod = self.rules.start_balance
        self.dd_limit = self.rules.start_balance - self.rules.eod_trailing_dd

    # --- intraday ---
    def check_equity(self, equity: float):
        """Called every bar with marked-to-market equity. Trailing DD is enforced live."""
        if equity <= self.dd_limit and not self.failed:
            self.failed = True
            self.fail_reason = (f"Trailing drawdown breached intraday: "
                                f"equity {equity:.2f} <= {self.dd_limit:.2f}")

    def on_realized(self, pnl: float):
        self.balance += pnl
        self.day_realized += pnl
        if (self.rules.daily_loss_limit is not None
                and self.day_realized <= -self.rules.daily_loss_limit):
            self.locked_today = True   # soft breach: engine flattens, no entries until next day

    def can_enter(self) -> bool:
        return not (self.failed or self.passed or self.locked_today)

    # --- end of trading day (17:00 ET) ---
    def end_of_day(self, traded_today: bool):
        if traded_today:
            self.trading_days += 1
            self.daily_pnls.append(self.day_realized)
        if self.balance > self.hwm_eod:
            self.hwm_eod = self.balance
            new_limit = self.hwm_eod - self.rules.eod_trailing_dd
            lock_at = self.rules.start_balance + self.rules.drawdown_lock_offset
            self.dd_limit = min(max(self.dd_limit, new_limit), lock_at)
        self.day_realized = 0.0
        self.locked_today = False
        self._check_pass()

    def _check_pass(self):
        profit = self.balance - self.rules.start_balance
        if profit < self.rules.profit_target or self.trading_days < self.rules.min_trading_days:
            return
        if self.rules.consistency_pct is not None and self.daily_pnls:
            best = max(self.daily_pnls)
            if best > 0 and profit > 0 and best / profit > self.rules.consistency_pct:
                return   # target hit but consistency blocks the pass; keep trading
        self.passed = True


def hft_rule_report(trades) -> dict:
    """>50% of trades AND >50% of profit must come from holds >10s.
    On 1-min bars every hold is >=60s, but we verify rather than assume."""
    if not trades:
        return {"pct_trades_gt_10s": None, "pct_profit_gt_10s": None, "compliant": None}
    long_holds = [t for t in trades if t.hold_seconds > 10]
    profit_pos = sum(t.pnl for t in trades if t.pnl > 0) or 1e-9
    profit_long = sum(t.pnl for t in long_holds if t.pnl > 0)
    pt, pp = len(long_holds) / len(trades), profit_long / profit_pos
    return {"pct_trades_gt_10s": pt, "pct_profit_gt_10s": pp,
            "compliant": pt > 0.5 and pp > 0.5}
