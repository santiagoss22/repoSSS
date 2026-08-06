from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class BotSettings:
    strategy_id: str = "bot-RSIs"
    risk_management_version: int = 3
    manual_large_fraction: float = 0.50
    minimum_cash_eur: float = 2_000.0
    minimum_trade_eur: float = 500.0
    sell_gain: float = 0.04
    fee_rate: float = 0.006
    slippage_rate: float = 0.001
    risk_per_trade: float = 0.005
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
    max_open_lots: int = 8
    max_spread: float = 0.002
    max_open_risk: float = 0.04
    normal_buy_eur: float = 1_000.0
    high_volatility_buy_eur: float = 1_000.0
    loss_streak_pause_after: int = 2
    loss_streak_halt_after: int = 10
    loss_streak_pause_ticks: int = 120
    drawdown_reduce_size: float = 0.05
    drawdown_block_buys: float = 0.08
    drawdown_halt: float = 0.10
    chart_range_eur: float = 2_000.0
    atr_stop_multiplier: float = 1.50
    atr_target_multiplier: float = 2.25
    atr_trailing_multiplier: float = 1.50
    minimum_atr_stop: float = 0.02
    maximum_atr_stop: float = 0.08
    cost_safety_margin: float = 0.01
    buy_rsi_6: float = 20.0
    buy_rsi_12: float = 35.0
    buy_rsi_24_min: float = 40.0
    buy_rsi_24_max: float = 55.0
    sell_rsi_6: float = 80.0
    sell_rsi_12: float = 65.0
    sell_rsi_24: float = 60.0
    trend_fast_ema: int = 50
    trend_slow_ema: int = 200
    bos_lookback: int = 12
    bos_volume_multiplier: float = 1.30
    bos_volume_lookback: int = 12

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict) -> "BotSettings":
        values = dict(values)
        values["bos_lookback"] = 12
        values["bos_volume_multiplier"] = 1.30
        values["bos_volume_lookback"] = 12
        legacy_risk_management = "risk_management_version" not in values
        version = int(values.get("risk_management_version", 0))
        if version < 2:
            values["risk_management_version"] = 2
            if values.get("risk_per_trade", 0.01) == 0.01:
                values["risk_per_trade"] = 0.005
        if version < 3:
            values["risk_management_version"] = 3
            if values.get("max_open_lots", 4) == 4:
                values["max_open_lots"] = 8
            if values.get("normal_buy_eur", 2_000.0) == 2_000.0:
                values["normal_buy_eur"] = 1_000.0
        if values.get("minimum_buy_price_drop", 0) < 0.012:
            # La versión anterior solo esperaba tres segundos y podía agrupar
            # varias entradas casi al mismo precio.
            values["buy_spacing_ticks"] = 15
            values["minimum_buy_price_drop"] = 0.012
        if legacy_risk_management:
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
