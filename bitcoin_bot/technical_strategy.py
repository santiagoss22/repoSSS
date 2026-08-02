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


class MultiIndicatorStrategy:
    """Opera giros extremos de RSI usando únicamente velas cerradas de 1h."""

    def __init__(self) -> None:
        self.buy_armed = False
        self.sell_armed = False
        self._last_bar_key: tuple[int, float] | None = None

    def evaluate(
        self,
        hourly: list[float],
        five_minute: list[float] | None = None,
        daily: list[float] | None = None,
        hourly_highs: list[float] | None = None,
        hourly_lows: list[float] | None = None,
    ) -> TechnicalSignal:
        if len(hourly) < 26:
            return TechnicalSignal(
                "ESPERAR", "Indicadores calentando", 0, 50.0, 0.0, 0.0
            )
        rsi_6 = rsi(hourly, 6)
        rsi_12 = rsi(hourly, 12)
        rsi_24 = rsi(hourly, 24)
        ema_9 = ema(hourly, 9)
        histogram = macd_histogram(hourly)
        volatility = atr_percent(hourly, hourly_highs, hourly_lows)
        size_factor = 0.0 if volatility >= 0.05 else 0.5 if volatility >= 0.03 else 1.0
        values = (rsi_6[-1], rsi_12[-1], rsi_24[-1])
        common = dict(
            rsi=values[1], volatility=volatility, size_factor=size_factor,
            rsi_6=values[0], rsi_12=values[1], rsi_24=values[2],
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

        was_buy_armed = self.buy_armed
        was_sell_armed = self.sell_armed
        oversold = values[0] < 15 and values[1] < 25 and values[2] < 35
        overbought = values[0] > 80 and values[1] > 65 and values[2] > 60
        if oversold:
            self.buy_armed = True
            self.sell_armed = False
        if overbought:
            self.sell_armed = True
            self.buy_armed = False

        buy_turn = (
            was_buy_armed
            and rsi_6[-1] > rsi_6[-2]
            and rsi_12[-1] >= rsi_12[-2]
            and hourly[-1] > ema_9[-1]
        )
        sell_turn = (
            was_sell_armed
            and rsi_6[-1] < rsi_6[-2]
            and rsi_12[-1] <= rsi_12[-2]
            and hourly[-1] < ema_9[-1]
        )
        bearish_confirmation = hourly[-1] < ema_9[-1] and histogram[-1] < 0

        if size_factor == 0:
            return TechnicalSignal(
                "ESPERAR", "volatilidad extrema", 0,
                bearish_confirmation=bearish_confirmation,
                buy_armed=self.buy_armed, sell_armed=self.sell_armed,
                **{**common, "size_factor": 0.0},
            )
        if buy_turn:
            self.buy_armed = False
            return TechnicalSignal(
                "COMPRAR", "Giro RSI alcista · cierre 1h sobre EMA(9)", 3,
                ema_confirmation=True,
                bearish_confirmation=bearish_confirmation,
                buy_armed=False, sell_armed=self.sell_armed, **common,
            )
        if sell_turn:
            self.sell_armed = False
            return TechnicalSignal(
                "VENDER", "Giro RSI bajista · cierre 1h bajo EMA(9)", 3,
                bearish_confirmation=True,
                buy_armed=self.buy_armed, sell_armed=False, **common,
            )

        if self.buy_armed and values[2] >= 50:
            self.buy_armed = False
        if self.sell_armed and values[2] <= 50:
            self.sell_armed = False
        status = (
            "Compra preparada · esperando giro RSI y EMA(9)"
            if self.buy_armed else
            "Venta preparada · esperando giro RSI y EMA(9)"
            if self.sell_armed else
            "RSI 1h sin señal extrema"
        )
        return TechnicalSignal(
            "ESPERAR", status, int(oversold or overbought),
            bearish_confirmation=bearish_confirmation,
            buy_armed=self.buy_armed, sell_armed=self.sell_armed, **common,
        )
