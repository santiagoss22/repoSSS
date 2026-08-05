from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import json
import math
import random
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from bitcoin_bot.config import BotSettings
from bitcoin_bot.simulator import PaperAccount
from bitcoin_bot.strategy_loader import create_strategy
from bitcoin_bot.technical_strategy import build_trade_risk_plan


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
    stop_exits: int
    average_win_eur: float
    average_loss_eur: float
    profit_factor: float
    max_losing_streak: int
    expectancy_eur: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    exposure_percent: float = 0.0
    sale_pnls: tuple[float, ...] = ()


@dataclass(frozen=True)
class RobustnessResult:
    profitable_folds: int
    folds: int
    walk_forward_average_percent: float
    stress_150_percent: float
    stress_200_percent: float
    monte_carlo_p05_equity: float


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
    if len(prices) < settings.trend_slow_ema + 2:
        raise ValueError("No hay suficientes precios para ejecutar el backtest.")
    account = PaperAccount(
        minimum_cash_eur=settings.minimum_cash_eur,
        minimum_trade_eur=settings.minimum_trade_eur,
        max_position_fraction=settings.max_position_fraction,
        max_open_lots=settings.max_open_lots,
    )
    strategy = create_strategy(settings)
    observed: list[float] = []
    equity_curve: list[float] = []
    invested_bars = 0
    for price in prices:
        observed.append(price)
        account.record_equity(price)
        equity_curve.append(account.equity(price))
        invested_bars += bool(account.lots)
        if account.cooldown_remaining > 0:
            account.cooldown_remaining -= 1
        if account.buy_cooldown_remaining > 0:
            account.buy_cooldown_remaining -= 1
        if account.post_sale_cooldown_remaining > 0:
            account.post_sale_cooldown_remaining -= 1
        if account.loss_streak_cooldown_remaining > 0:
            account.loss_streak_cooldown_remaining -= 1
        account.update_reentry_reference(
            price, settings.stable_reference_ticks,
            settings.stable_reference_range,
        )
        technical = strategy.evaluate(observed, observed, [])
        rebound_failed = account.update_defensive_exit(
            price, technical.bearish_confirmation,
            settings.stable_reference_ticks, settings.stable_reference_range,
            settings.rebound_from_floor,
        )
        stopped, stop_kind = account.stopped_lots(
            price,
            settings.stop_loss,
            settings.trailing_activation,
            settings.trailing_distance,
        )
        if stopped:
            trade = account.sell_selected_lots(
                stopped, price, stop_kind,
                settings.fee_rate, settings.slippage_rate,
            )
            account.record_sale_result(
                trade.pnl_eur,
                settings.loss_streak_pause_after,
                settings.loss_streak_pause_ticks,
            )
            account.cooldown_remaining = settings.cooldown_ticks
            account.register_sale(price, settings.post_sale_cooldown_ticks)
            continue
        defensive = []
        if (
            account.bearish_confirmation_count
            >= settings.bearish_confirmation_ticks
        ):
            defensive = account.losing_lots(price, settings.defensive_loss)
        if rebound_failed:
            selected_ids = {id(lot) for lot in defensive}
            defensive.extend(
                lot for lot in account.lots
                if id(lot) not in selected_ids
                and price < (lot.entry_price_eur or lot.cost_basis_eur / lot.bitcoin)
            )
        if defensive:
            trade = account.sell_selected_lots(
                defensive, price, "Venta defensiva",
                settings.fee_rate, settings.slippage_rate,
            )
            account.record_sale_result(
                trade.pnl_eur,
                settings.loss_streak_pause_after,
                settings.loss_streak_pause_ticks,
            )
            account.register_sale(price, settings.post_sale_cooldown_ticks)
            continue
        profitable = account.profitable_lots(
            price,
            settings.sell_gain,
            settings.fee_rate,
            settings.slippage_rate,
        )
        if profitable:
            trade = account.sell_profitable_lots(
                price,
                settings.sell_gain,
                "Backtest por lotes",
                fee_rate=settings.fee_rate,
                slippage_rate=settings.slippage_rate,
            )
            account.record_sale_result(
                trade.pnl_eur,
                settings.loss_streak_pause_after,
                settings.loss_streak_pause_ticks,
            )
            account.register_sale(price, settings.post_sale_cooldown_ticks)
            continue
        action = technical.action
        if action == "VENDER":
            profitable = account.profitable_lots(
                price, 0.0, settings.fee_rate, settings.slippage_rate
            )
            if profitable:
                trade = account.sell_profitable_lots(
                    price,
                    0.0,
                    "Salida técnica confirmada en 1h",
                    fee_rate=settings.fee_rate,
                    slippage_rate=settings.slippage_rate,
                )
                account.record_sale_result(
                    trade.pnl_eur,
                    settings.loss_streak_pause_after,
                    settings.loss_streak_pause_ticks,
                )
            continue
        if (
            action == "COMPRAR"
            and account.cooldown_remaining == 0
            and account.loss_streak_cooldown_remaining == 0
            and account.consecutive_losses < settings.loss_streak_halt_after
            and account.max_drawdown < settings.drawdown_block_buys
            and account.can_buy(price, fee_rate=settings.fee_rate)
        ):
            plan = build_trade_risk_plan(
                technical.volatility, settings, settings.fee_rate
            )
            if not plan.covers_costs:
                continue
            reduced = (
                technical.size_factor < 1
                or account.max_drawdown >= settings.drawdown_reduce_size
            )
            size_cap = (
                settings.high_volatility_buy_eur
                if reduced else settings.normal_buy_eur
            )
            budget = min(
                size_cap,
                account.risk_sized_value(
                    price, settings.risk_per_trade, plan.stop_loss,
                    settings.fee_rate, settings.slippage_rate,
                ),
            )
            if budget < settings.minimum_trade_eur * (1 + settings.fee_rate):
                continue
            maximum_risk = account.initial_cash_eur * settings.max_open_risk
            if not account.can_add_risk(
                price,
                budget,
                plan.stop_loss,
                maximum_risk,
                settings.fee_rate,
                settings.slippage_rate,
            ):
                continue
            value = budget / (1 + settings.fee_rate)
            try:
                account.buy(
                    price,
                    value,
                    "Backtest",
                    max_fraction=settings.max_position_fraction,
                    fee_rate=settings.fee_rate,
                    slippage_rate=settings.slippage_rate,
                    stop_loss_rate=plan.stop_loss,
                    target_profit_rate=plan.target_profit,
                    trailing_activation_rate=plan.trailing_activation,
                    trailing_distance_rate=plan.trailing_distance,
                )
            except ValueError:
                # Una señal válida puede quedar por debajo del mínimo al rozar
                # la reserva o la exposición máxima; el backtest continúa.
                pass
    ending = account.equity(prices[-1])
    sales = [trade for trade in account.trades if trade.side == "VENTA"]
    winning_sales = sum(trade.pnl_eur > 0 for trade in sales)
    losing_sales = sum(trade.pnl_eur <= 0 for trade in sales)
    win_rate = winning_sales / len(sales) * 100 if sales else 0.0
    wins = [trade.pnl_eur for trade in sales if trade.pnl_eur > 0]
    losses = [-trade.pnl_eur for trade in sales if trade.pnl_eur <= 0]
    average_win = sum(wins) / len(wins) if wins else 0.0
    average_loss = sum(losses) / len(losses) if losses else 0.0
    profit_factor = sum(wins) / sum(losses) if losses else float("inf") if wins else 0.0
    current_streak = max_streak = 0
    for trade in sales:
        current_streak = current_streak + 1 if trade.pnl_eur <= 0 else 0
        max_streak = max(max_streak, current_streak)
    buy_hold_return = (prices[-1] / prices[0] - 1) * 100
    return_percent = (ending / account.initial_cash_eur - 1) * 100
    years = max(len(prices) - 1, 1) / (24 * 365)
    annualized = ((ending / account.initial_cash_eur) ** (1 / years) - 1) * 100
    expectancy = sum(trade.pnl_eur for trade in sales) / len(sales) if sales else 0.0
    returns = [
        current / previous - 1
        for previous, current in zip(equity_curve, equity_curve[1:])
        if previous > 0
    ]
    mean_return = sum(returns) / len(returns) if returns else 0.0
    variance = (
        sum((value - mean_return) ** 2 for value in returns) / len(returns)
        if returns else 0.0
    )
    downside = [min(value, 0.0) for value in returns]
    downside_deviation = math.sqrt(
        sum(value * value for value in downside) / len(downside)
    ) if downside else 0.0
    annualizer = math.sqrt(24 * 365)
    sharpe = mean_return / math.sqrt(variance) * annualizer if variance > 0 else 0.0
    sortino = mean_return / downside_deviation * annualizer if downside_deviation > 0 else 0.0
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
        sum("stop" in trade.reason.lower() for trade in sales),
        average_win,
        average_loss,
        profit_factor,
        max_streak,
        expectancy,
        sharpe,
        sortino,
        invested_bars / len(prices) * 100,
        tuple(trade.pnl_eur for trade in sales),
    )


def evaluate_robustness(prices: list[float], settings: BotSettings) -> RobustnessResult:
    """Pruebas deterministas de periodos separados, costes y orden de resultados."""
    minimum = settings.trend_slow_ema + 2
    fold_size = max(minimum, len(prices) // 5)
    folds = [prices[index:index + fold_size] for index in range(0, len(prices), fold_size)]
    folds = [fold for fold in folds if len(fold) >= minimum][-5:]
    fold_results = [run_backtest(fold, settings) for fold in folds]
    base = run_backtest(prices, settings)
    stress_150 = run_backtest(
        prices,
        replace(
            settings,
            fee_rate=settings.fee_rate * 1.5,
            slippage_rate=settings.slippage_rate * 1.5,
        ),
    )
    stress_200 = run_backtest(
        prices,
        replace(
            settings,
            fee_rate=settings.fee_rate * 2,
            slippage_rate=settings.slippage_rate * 2,
        ),
    )
    rng = random.Random(42)
    outcomes = []
    if base.sale_pnls:
        for _ in range(1_000):
            outcomes.append(
                base.starting_equity
                + sum(rng.choice(base.sale_pnls) for _ in base.sale_pnls)
            )
        outcomes.sort()
        p05 = outcomes[int(len(outcomes) * 0.05)]
    else:
        p05 = base.ending_equity
    return RobustnessResult(
        sum(result.return_percent > 0 for result in fold_results),
        len(fold_results),
        sum(result.return_percent for result in fold_results) / len(fold_results)
        if fold_results else 0.0,
        stress_150.return_percent,
        stress_200.return_percent,
        p05,
    )
