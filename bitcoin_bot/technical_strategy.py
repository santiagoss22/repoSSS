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


class MultiIndicatorStrategy:
    """Compra retrocesos dentro de una tendencia positiva confirmada."""

    def evaluate(
        self,
        hourly: list[float],
        five_minute: list[float] | None = None,
        daily: list[float] | None = None,
        hourly_highs: list[float] | None = None,
        hourly_lows: list[float] | None = None,
    ) -> TechnicalSignal:
        five_minute = five_minute or hourly
        daily = daily or []
        if len(hourly) < 35 or len(five_minute) < 21:
            return TechnicalSignal(
                "ESPERAR", "Indicadores calentando", 0, 50.0, 0.0, 0.0
            )

        trend_ok = True
        trend_text = "tendencia provisional"
        if len(daily) >= 200:
            daily_50 = ema(daily, 50)
            daily_200 = ema(daily, 200)
            trend_ok = daily[-1] > daily_200[-1] and daily_50[-1] > daily_50[-2]
            trend_text = "tendencia diaria positiva" if trend_ok else "filtro diario bajista"

        current_rsi = rsi(hourly, 14)
        lower, _, _ = bollinger(hourly, 20)
        histogram = macd_histogram(hourly)
        conditions = {
            "RSI recuperándose": 30 <= current_rsi[-1] <= 58
            and current_rsi[-1] > current_rsi[-2],
            "cerca de Bollinger inferior": hourly[-1] <= lower * 1.012,
            "MACD mejorando": histogram[-1] > histogram[-2],
        }
        score = sum(conditions.values())
        fast = ema(five_minute, 9)
        slow = ema(five_minute, 21)
        confirmation = fast[-1] > slow[-1] or five_minute[-1] > fast[-1]
        bearish_confirmation = fast[-1] < slow[-1] and histogram[-1] < 0
        volatility = atr_percent(hourly, hourly_highs, hourly_lows)
        size_factor = 0.0 if volatility >= 0.05 else 0.5 if volatility >= 0.03 else 1.0
        matched = ", ".join(name for name, valid in conditions.items() if valid) or "sin confirmaciones"

        if not trend_ok:
            return TechnicalSignal("ESPERAR", trend_text, score, current_rsi[-1], volatility, 0.0, False, bearish_confirmation)
        if size_factor == 0:
            return TechnicalSignal("ESPERAR", "volatilidad extrema", score, current_rsi[-1], volatility, 0.0, False, bearish_confirmation)
        if score >= 2 and confirmation:
            return TechnicalSignal(
                "COMPRAR", f"{matched} · confirmación EMA 5m", score,
                current_rsi[-1], volatility, size_factor, True, False,
            )
        return TechnicalSignal(
            "ESPERAR", f"{trend_text} · {score}/3 condiciones", score,
            current_rsi[-1], volatility, size_factor, False,
            bearish_confirmation,
        )
