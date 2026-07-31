from __future__ import annotations

from dataclasses import dataclass
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from bitcoin_bot.config import BotSettings
from bitcoin_bot.simulator import PaperAccount, RecoveryController, TrendConfirmation


@dataclass(frozen=True)
class BacktestResult:
    starting_equity: float
    ending_equity: float
    return_percent: float
    realized_profit: float
    total_fees: float
    max_drawdown_percent: float
    trades: int


def download_coinbase_daily_prices(limit: int = 300) -> list[float]:
    query = urlencode({"granularity": "86400"})
    url = f"https://api.exchange.coinbase.com/products/BTC-EUR/candles?{query}"
    request = Request(url, headers={"User-Agent": "BitcoinPaperBot/1.0"})
    with urlopen(request, timeout=15) as response:
        candles = json.load(response)
    ordered = sorted(candles[:limit], key=lambda candle: candle[0])
    return [float(candle[4]) for candle in ordered]


def run_backtest(prices: list[float], settings: BotSettings) -> BacktestResult:
    if len(prices) < settings.confirmation_ticks + 2:
        raise ValueError("No hay suficientes precios para ejecutar el backtest.")
    account = PaperAccount(
        minimum_cash_eur=settings.minimum_cash_eur,
        minimum_trade_eur=settings.minimum_trade_eur,
    )
    confirmation = TrendConfirmation(
        confirmation_ticks=settings.confirmation_ticks,
        sell_gain=settings.sell_gain,
        reference_expiry_ticks=settings.reference_expiry_ticks,
    )
    recovery = RecoveryController(
        loss_trigger=settings.recovery_loss_trigger,
        stable_ticks=settings.recovery_stable_ticks,
        stable_range=settings.recovery_range,
    )
    for price in prices:
        drawdown = account.record_equity(price)
        recovery.update(account, price)
        include_frozen = not recovery.active
        profitable = account.profitable_lots(
            price,
            settings.sell_gain,
            settings.fee_rate,
            settings.slippage_rate,
            include_frozen=include_frozen,
        )
        if profitable:
            account.sell_profitable_lots(
                price,
                settings.sell_gain,
                "Backtest por lotes",
                fee_rate=settings.fee_rate,
                slippage_rate=settings.slippage_rate,
                include_frozen=include_frozen,
            )
            confirmation.reset()
        action, _ = confirmation.update(price, False)
        if (
            action == "COMPRAR"
            and (drawdown < settings.max_drawdown or recovery.enabled)
            and account.can_buy(price, fee_rate=settings.fee_rate)
        ):
            account.buy(
                price,
                account.equity(price) * settings.buy_fraction,
                "Backtest",
                max_fraction=settings.buy_fraction,
                fee_rate=settings.fee_rate,
                slippage_rate=settings.slippage_rate,
            )
    ending = account.equity(prices[-1])
    return BacktestResult(
        account.initial_cash_eur,
        ending,
        (ending / account.initial_cash_eur - 1) * 100,
        account.realized_profit_eur,
        account.total_fees_eur,
        account.max_drawdown * 100,
        len(account.trades),
    )
