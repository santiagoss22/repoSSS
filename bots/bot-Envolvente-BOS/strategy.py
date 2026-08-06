from __future__ import annotations

from dataclasses import dataclass
from math import sqrt


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(alpha * value + (1 - alpha) * result[-1])
    return result


def rsi(values: list[float], period: int = 14) -> list[float]:
    if len(values) < 2:
        return [50.0] * len(values)
    gains = [0.0]
    losses = [0.0]
    for previous, current in zip(values, values[1:]):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    average_gain = sum(gains[1 : period + 1]) / min(period, len(values) - 1)
    average_loss = sum(losses[1 : period + 1]) / min(period, len(values) - 1)
    output = [50.0] * min(period, len(values))
    for index in range(period, len(values)):
        if index > period:
            average_gain = (average_gain * (period - 1) + gains[index]) / period
            average_loss = (average_loss * (period - 1) + losses[index]) / period
        value = 100.0 if average_loss == 0 else 100 - 100 / (1 + average_gain / average_loss)
        output.append(value)
    return output[: len(values)]


def bollinger(values: list[float], period: int = 20, deviations: float = 2.0) -> tuple[float, float, float]:
    window = values[-period:]
    middle = sum(window) / len(window)
    variance = sum((value - middle) ** 2 for value in window) / len(window)
    distance = sqrt(variance) * deviations
    return middle - distance, middle, middle + distance


def macd_histogram(values: list[float]) -> list[float]:
    fast = ema(values, 12)
    slow = ema(values, 26)
    line = [a - b for a, b in zip(fast, slow)]
    signal = ema(line, 9)
    return [a - b for a, b in zip(line, signal)]


def atr_percent(closes: list[float], highs: list[float] | None = None,
                lows: list[float] | None = None, period: int = 14) -> float:
    if len(closes) < 2:
        return 0.0
    highs = highs or closes
    lows = lows or closes
    ranges = [
        max(highs[index] - lows[index], abs(highs[index] - closes[index - 1]),
            abs(lows[index] - closes[index - 1]))
        for index in range(1, len(closes))
    ]
    return (sum(ranges[-period:]) / min(period, len(ranges))) / closes[-1]


@dataclass(frozen=True)
class TechnicalSignal:
    action: str
    status: str
    score: int
    rsi: float
    volatility: float
    size_factor: float
    ema_confirmation: bool = False
    bearish_confirmation: bool = False
    rsi_6: float = 50.0
    rsi_12: float = 50.0
    rsi_24: float = 50.0
    buy_armed: bool = False
    sell_armed: bool = False


@dataclass(frozen=True)
class TradeRiskPlan:
    stop_loss: float
    target_profit: float
    trailing_activation: float
    trailing_distance: float
    expected_move: float
    covers_costs: bool


def build_trade_risk_plan(volatility: float, settings, fee_rate: float) -> TradeRiskPlan:
    """Congela salidas coherentes con la volatilidad y los costes de entrada."""
    stop = min(
        getattr(settings, "maximum_atr_stop", 0.08),
        max(
            getattr(settings, "minimum_atr_stop", 0.02),
            volatility * getattr(settings, "atr_stop_multiplier", 1.5),
        ),
    )
    expected_move = volatility * getattr(settings, "atr_target_multiplier", 2.25)
    round_trip_cost = 2 * fee_rate + 2 * getattr(settings, "slippage_rate", 0.0)
    target = max(expected_move, stop * 1.5, round_trip_cost + getattr(settings, "cost_safety_margin", 0.01))
    trailing_distance = min(
        stop,
        max(0.01, volatility * getattr(settings, "atr_trailing_multiplier", 1.5)),
    )
    return TradeRiskPlan(
        stop, target, max(stop, target / 2), trailing_distance, expected_move,
        expected_move >= round_trip_cost + getattr(settings, "cost_safety_margin", 0.01),
    )


class MultiIndicatorStrategy:
    """Ruptura de estructura con volumen sobre velas cerradas de 1h."""

    def __init__(self, settings=None) -> None:
        self.buy_armed = False
        self.sell_armed = False
        self._last_bar_key: tuple[int, float] | None = None
        self.phase = "idle"
        self.structure_level = 0.0
        self.invalidation_level = 0.0
        self.setup_age = 0
        self.lookback = getattr(settings, "bos_lookback", 20)
        self.volume_multiplier = getattr(settings, "bos_volume_multiplier", 1.3)
        self.volume_lookback = getattr(settings, "bos_volume_lookback", 12)
        self.retest_tolerance = getattr(settings, "bos_retest_tolerance", 0.003)
        self.maximum_setup_bars = getattr(settings, "bos_max_setup_bars", 12)

    def evaluate(
        self,
        hourly: list[float],
        five_minute: list[float] | None = None,
        daily: list[float] | None = None,
        hourly_highs: list[float] | None = None,
        hourly_lows: list[float] | None = None,
        hourly_opens: list[float] | None = None,
        hourly_volumes: list[float] | None = None,
    ) -> TechnicalSignal:
        minimum = self.lookback + 1
        if len(hourly) < minimum:
            return TechnicalSignal(
                "ESPERAR", "Estructura calentando", 0, 50.0, 0.0, 0.0
            )
        opens = hourly_opens or [hourly[0], *hourly[:-1]]
        highs = hourly_highs or [max(open_, close) for open_, close in zip(opens, hourly)]
        lows = hourly_lows or [min(open_, close) for open_, close in zip(opens, hourly)]
        volatility = atr_percent(hourly, hourly_highs, hourly_lows)
        size_factor = 0.0 if volatility >= 0.05 else 0.5 if volatility >= 0.03 else 1.0
        common = dict(
            rsi=50.0, volatility=volatility, size_factor=size_factor,
            rsi_6=50.0, rsi_12=50.0, rsi_24=50.0,
        )

        # En datos en vivo la interfaz puede consultar varias veces la misma
        # vela. Solo una vela nueva puede armar o ejecutar una señal.
        bar_key = (len(hourly), hourly[-1])
        if bar_key == self._last_bar_key:
            return TechnicalSignal(
                "ESPERAR", "Esperando cierre de vela 1h", 0,
                buy_armed=self.buy_armed, sell_armed=self.sell_armed,
                **common,
            )
        self._last_bar_key = bar_key
        prior_high = max(highs[-self.lookback - 1:-1])
        prior_low = min(lows[-self.lookback - 1:-1])
        volumes = hourly_volumes or []
        has_volume = len(volumes) >= self.volume_lookback + 1
        average_volume = (
            sum(volumes[-self.volume_lookback - 1:-1]) / self.volume_lookback
            if has_volume else 0.0
        )
        volume_confirmed = (
            has_volume and average_volume > 0
            and volumes[-1] >= average_volume * self.volume_multiplier
        )
        bullish_breakout = hourly[-1] > prior_high and hourly[-1] > opens[-1]
        bearish_breakout = hourly[-1] < prior_low and hourly[-1] < opens[-1]
        bearish_confirmation = bearish_breakout and volume_confirmed

        if size_factor == 0:
            return TechnicalSignal(
                "ESPERAR", "volatilidad extrema", 0,
                bearish_confirmation=bearish_confirmation,
                buy_armed=self.buy_armed, sell_armed=self.sell_armed,
                **{**common, "size_factor": 0.0},
            )
        if bullish_breakout and volume_confirmed:
            return TechnicalSignal(
                "COMPRAR", "Ruptura alcista de 20h con volumen confirmado", 4,
                ema_confirmation=True,
                bearish_confirmation=bearish_confirmation,
                buy_armed=False, sell_armed=self.sell_armed, **common,
            )
        if bearish_breakout and volume_confirmed:
            return TechnicalSignal(
                "VENDER", "Ruptura bajista de 20h con volumen confirmado", 4,
                bearish_confirmation=True,
                buy_armed=self.buy_armed, sell_armed=False, **common,
            )

        status = (
            "Sin volumen real: la liquidez no puede confirmarse"
            if not has_volume else
            f"Ruptura sin volumen suficiente (necesita {self.volume_multiplier:.1f}× media 12h)"
            if bullish_breakout or bearish_breakout else
            f"Buscando ruptura del rango de 20h con volumen ≥ {self.volume_multiplier:.1f}× media 12h"
        )
        return TechnicalSignal(
            "ESPERAR", status, int(bullish_breakout or bearish_breakout),
            bearish_confirmation=bearish_confirmation,
            buy_armed=self.buy_armed, sell_armed=self.sell_armed, **common,
        )
