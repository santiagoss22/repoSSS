from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class BotSettings:
    risk_management_version: int = 1
    manual_large_fraction: float = 0.50
    minimum_cash_eur: float = 2_000.0
    minimum_trade_eur: float = 500.0
    sell_gain: float = 0.04
    fee_rate: float = 0.006
    slippage_rate: float = 0.001
    risk_per_trade: float = 0.01
    stop_loss: float = 0.06
    trailing_activation: float = 0.07
    trailing_distance: float = 0.04
    daily_loss_limit: float = 0.02
    weekly_loss_limit: float = 0.04
    cooldown_ticks: int = 15
    buy_spacing_ticks: int = 15
    minimum_buy_price_drop: float = 0.012
    max_position_fraction: float = 0.80
    max_open_lots: int = 4
    max_spread: float = 0.002

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict) -> "BotSettings":
        values = dict(values)
        if values.get("minimum_buy_price_drop", 0) < 0.012:
            # La versión anterior solo esperaba tres segundos y podía agrupar
            # varias entradas casi al mismo precio.
            values["buy_spacing_ticks"] = 15
            values["minimum_buy_price_drop"] = 0.012
        if "risk_management_version" not in values:
            # Migra la estrategia antigua de recuperación a los nuevos
            # valores seguros, conservando comisiones y preferencias generales.
            values.pop("sell_gain", None)
        elif values.get("sell_gain") == 0.12:
            # Migra el objetivo anterior, demasiado lejano para la operativa
            # frecuente de esta simulación, sin pisar valores personalizados.
            values["sell_gain"] = 0.04
        if values.get("max_position_fraction") == 0.60:
            values["max_position_fraction"] = 0.80
        allowed = cls.__dataclass_fields__
        return cls(**{key: value for key, value in values.items() if key in allowed})
