from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
    winning_sales: int
    losing_sales: int
    win_rate_percent: float
    buy_hold_return_percent: float
    excess_return_percent: float
    annualized_return_percent: float


def download_coinbase_daily_prices(limit: int = 1_095) -> list[float]:
    """Descarga hasta tres años en bloques compatibles con Coinbase."""
    limit = max(1, min(limit, 1_095))
    end = datetime.now(timezone.utc)
    candles_by_time: dict[int, list] = {}
    while len(candles_by_time) < limit:
        batch_days = min(300, limit - len(candles_by_time))
        start = end - timedelta(days=batch_days)
        query = urlencode(
            {
                "granularity": "86400",
                "start": start.isoformat(),
                "end": end.isoformat(),
            }
        )
        url = f"https://api.exchange.coinbase.com/products/BTC-EUR/candles?{query}"
        request = Request(url, headers={"User-Agent": "BitcoinPaperBot/1.0"})
        with urlopen(request, timeout=15) as response:
            candles = json.load(response)
        if not candles:
            break
        for candle in candles:
            candles_by_time[int(candle[0])] = candle
        end = start - timedelta(seconds=1)
    ordered = sorted(candles_by_time.values(), key=lambda candle: candle[0])[-limit:]
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
    sales = [trade for trade in account.trades if trade.side == "VENTA"]
    winning_sales = sum(trade.pnl_eur > 0 for trade in sales)
    losing_sales = sum(trade.pnl_eur <= 0 for trade in sales)
    win_rate = winning_sales / len(sales) * 100 if sales else 0.0
    buy_hold_return = (prices[-1] / prices[0] - 1) * 100
    return_percent = (ending / account.initial_cash_eur - 1) * 100
    years = max(len(prices) - 1, 1) / 365
    annualized = ((ending / account.initial_cash_eur) ** (1 / years) - 1) * 100
    return BacktestResult(
        account.initial_cash_eur,
        ending,
        return_percent,
        account.realized_profit_eur,
        account.total_fees_eur,
        account.max_drawdown * 100,
        len(account.trades),
        winning_sales,
        losing_sales,
        win_rate,
        buy_hold_return,
        return_percent - buy_hold_return,
        annualized,
    )
