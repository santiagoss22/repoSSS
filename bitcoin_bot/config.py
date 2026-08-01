from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class BotSettings:
    risk_management_version: int = 1
    manual_large_fraction: float = 0.50
    minimum_cash_eur: float = 2_000.0
    minimum_trade_eur: float = 500.0
    sell_gain: float = 0.12
    fee_rate: float = 0.006
    slippage_rate: float = 0.001
    risk_per_trade: float = 0.01
    stop_loss: float = 0.06
    trailing_activation: float = 0.07
    trailing_distance: float = 0.04
    daily_loss_limit: float = 0.02
    weekly_loss_limit: float = 0.04
    cooldown_ticks: int = 15
    max_position_fraction: float = 0.60
    max_spread: float = 0.002

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict) -> "BotSettings":
        values = dict(values)
        if "risk_management_version" not in values:
            # Migra la estrategia antigua de recuperación a los nuevos
            # valores seguros, conservando comisiones y preferencias generales.
            values.pop("sell_gain", None)
        allowed = cls.__dataclass_fields__
        return cls(**{key: value for key, value in values.items() if key in allowed})
