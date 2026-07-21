"""Round-trip cost model. Slippage on market/stop orders only; limit fills
require trade-through in the engine, so they carry no modeled slippage."""
from dataclasses import dataclass

from .contracts import ContractSpec


@dataclass
class CostModel:
    commission_rt: float          # $ per contract round turn
    slip_ticks_market: float
    spec: ContractSpec

    def entry_slippage(self, contracts: int) -> float:
        return self.slip_ticks_market * self.spec.tick_value * contracts

    def exit_slippage(self, contracts: int, order_type: str) -> float:
        t = self.slip_ticks_market if order_type in ("market", "stop") else 0.0
        return t * self.spec.tick_value * contracts

    def commission(self, contracts: int) -> float:
        return self.commission_rt * contracts

    def breakeven_winrate(self, stop_ticks: int, target_r: float) -> float:
        """Cost-adjusted breakeven win rate for the configured geometry, 1 contract."""
        risk = stop_ticks * self.spec.tick_value
        reward = target_r * risk
        c = self.commission_rt + 2 * self.slip_ticks_market * self.spec.tick_value
        # p*(reward - c) = (1-p)*(risk + c)  =>  p = (risk + c) / (risk + reward)
        return (risk + c) / (risk + reward)
