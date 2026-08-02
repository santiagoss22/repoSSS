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
    trailing_activation: float = 0.025
    trailing_distance: float = 0.015
    daily_loss_limit: float = 0.02
    weekly_loss_limit: float = 0.04
    cooldown_ticks: int = 15
    buy_spacing_ticks: int = 15
    minimum_buy_price_drop: float = 0.012
    post_sale_cooldown_ticks: int = 30
    reentry_pullback: float = 0.02
    stable_reference_ticks: int = 20
    stable_reference_range: float = 0.008
    defensive_loss: float = 0.03
    bearish_confirmation_ticks: int = 5
    rebound_from_floor: float = 0.015
    max_position_fraction: float = 0.80
    max_open_lots: int = 4
    max_spread: float = 0.002
    max_open_risk: float = 0.04
    normal_buy_eur: float = 2_000.0
    high_volatility_buy_eur: float = 1_000.0
    loss_streak_pause_after: int = 2
    loss_streak_halt_after: int = 10
    loss_streak_pause_ticks: int = 120
    drawdown_reduce_size: float = 0.05
    drawdown_block_buys: float = 0.08
    drawdown_halt: float = 0.10
    chart_range_eur: float = 2_000.0

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
        if values.get("trailing_activation") == 0.07:
            values["trailing_activation"] = 0.025
        if values.get("trailing_distance") == 0.04:
            values["trailing_distance"] = 0.015
        if values.get("loss_streak_halt_after") == 3:
            # Migra el antiguo bloqueo, demasiado sensible para evaluar la
            # estrategia durante periodos largos de simulación.
            values["loss_streak_halt_after"] = 10
        allowed = cls.__dataclass_fields__
        return cls(**{key: value for key, value in values.items() if key in allowed})
