"""Contract specifications. Tick sizes/values are exchange constants."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ContractSpec:
    symbol: str
    tick_size: float
    tick_value: float   # $ per tick per contract


SPECS = {
    "ES":  ContractSpec("ES",  0.25, 12.50),
    "MES": ContractSpec("MES", 0.25, 1.25),
}


def get_spec(symbol: str) -> ContractSpec:
    return SPECS[symbol.upper()]
