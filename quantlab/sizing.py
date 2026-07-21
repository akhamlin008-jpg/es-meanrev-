"""Position sizing. THE FORMULA PROPOSES, THE LIMITS DISPOSE:
the engine clamps every result to [0, max_contracts] and blocks entries that
could breach the trailing DD. Every sizing decision is logged with its inputs.

dd_frac_40pct: definition UNCONFIRMED (heatmap name, no formula attached).
Three candidate variants are implemented; the scheme raises until the config
names one explicitly. Do not guess -- confirm against the source material."""
from dataclasses import dataclass


@dataclass
class SizingContext:
    equity: float               # live equity, marked to market
    start_balance: float
    high_water_mark: float      # EOD basis
    dd_limit: float             # current trailing-DD kill line (account value)
    stop_ticks: int
    tick_value: float


class SizingScheme:
    name = "base"

    def contracts(self, ctx: SizingContext) -> int:
        raise NotImplementedError

    def log_row(self, ctx: SizingContext, n: int) -> dict:
        return {"scheme": self.name, "equity": ctx.equity, "hwm": ctx.high_water_mark,
                "dd_limit": ctx.dd_limit, "stop_ticks": ctx.stop_ticks, "contracts": n}


class FracPct(SizingScheme):
    """Working hypothesis for frac_2pct: risk `fraction` of live equity per trade.
    equity_basis='dd_allowance' instead risks a fraction of (equity - dd_limit),
    because 2% of nominal $50k = $1,000/trade vs a $2,000 total drawdown, which
    degenerates to always-max-size after clamping. Both bases are testable."""
    name = "frac_pct"

    def __init__(self, fraction: float, equity_basis: str = "nominal"):
        assert equity_basis in ("nominal", "dd_allowance")
        self.f, self.basis = fraction, equity_basis

    def contracts(self, ctx: SizingContext) -> int:
        base = ctx.equity if self.basis == "nominal" else max(ctx.equity - ctx.dd_limit, 0.0)
        risk_usd = self.f * base
        per_ct = ctx.stop_ticks * ctx.tick_value
        return max(int(risk_usd // per_ct), 0)


class DDFrac(SizingScheme):
    """UNCONFIRMED. Refuses to run without an explicit variant.

    floor_scaled:       risk_usd = base_frac * (equity - (1-param)*HWM)
                        (risk scales with distance to a (1-param) equity floor)
    allowance_fraction: risk_usd = param * (equity - dd_limit)
    fixed_f:            fixed fraction chosen OFFLINE so worst-case DD ~= param;
                        requires f_fixed supplied explicitly."""
    name = "dd_frac"

    def __init__(self, variant=None, param: float = 0.40,
                 base_frac: float = 0.02, f_fixed: float = None):
        if variant not in ("floor_scaled", "allowance_fraction", "fixed_f"):
            raise ValueError(
                "dd_frac_40pct definition is unconfirmed. Set sizing.dd_frac.variant "
                "explicitly after confirming against the heatmap/video source. "
                "Candidates: floor_scaled | allowance_fraction | fixed_f. "
                "They produce materially different sizes; do not guess.")
        self.variant, self.param = variant, param
        self.base_frac, self.f_fixed = base_frac, f_fixed

    def contracts(self, ctx: SizingContext) -> int:
        if self.variant == "floor_scaled":
            risk_usd = self.base_frac * max(ctx.equity - (1 - self.param) * ctx.high_water_mark, 0)
        elif self.variant == "allowance_fraction":
            risk_usd = self.param * max(ctx.equity - ctx.dd_limit, 0)
        else:
            if self.f_fixed is None:
                raise ValueError("fixed_f variant requires f_fixed derived offline.")
            risk_usd = self.f_fixed * ctx.equity
        return max(int(risk_usd // (ctx.stop_ticks * ctx.tick_value)), 0)


def build_sizer(cfg: dict) -> SizingScheme:
    scheme = cfg["scheme"]
    if scheme == "frac_pct":
        c = cfg["frac_pct"]
        return FracPct(c["fraction"], c.get("equity_basis", "nominal"))
    if scheme == "dd_frac":
        c = cfg["dd_frac"]
        return DDFrac(c.get("variant"), c.get("param", 0.40), f_fixed=c.get("f_fixed"))
    raise ValueError(f"Unknown sizing scheme: {scheme}")
