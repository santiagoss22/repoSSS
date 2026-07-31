from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class BotSettings:
    buy_fraction: float = 0.20
    manual_large_fraction: float = 0.50
    minimum_cash_eur: float = 2_000.0
    minimum_trade_eur: float = 500.0
    sell_gain: float = 0.025
    fee_rate: float = 0.006
    slippage_rate: float = 0.001
    max_drawdown: float = 0.10
    confirmation_ticks: int = 3
    reference_expiry_ticks: int = 300
    recovery_loss_trigger: float = 0.10
    recovery_stable_ticks: int = 15
    recovery_range: float = 0.01

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict) -> "BotSettings":
        allowed = cls.__dataclass_fields__
        return cls(**{key: value for key, value in values.items() if key in allowed})
