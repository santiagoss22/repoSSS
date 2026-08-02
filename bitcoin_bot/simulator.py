from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import random


@dataclass(frozen=True)
class Trade:
    timestamp: datetime
    side: str
    bitcoin: float
    price_eur: float
    value_eur: float
    reason: str
    fee_eur: float = 0.0
    pnl_eur: float = 0.0


@dataclass
class PositionLot:
    bitcoin: float
    cost_basis_eur: float
    timestamp: datetime = field(default_factory=datetime.now)
    frozen: bool = False
    entry_price_eur: float = 0.0
    peak_price_eur: float = 0.0
    stop_loss_rate: float = 0.0
    target_profit_rate: float = 0.0
    trailing_activation_rate: float = 0.0
    trailing_distance_rate: float = 0.0


@dataclass
class PaperAccount:
    initial_cash_eur: float = 10_000.0
    cash_eur: float = 10_000.0
    bitcoin: float = 0.0
    max_buy_fraction: float = 0.20
    max_position_fraction: float = 0.80
    max_open_lots: int = 4
    minimum_cash_eur: float = 2_000.0
    minimum_trade_eur: float = 500.0
    cost_basis_eur: float = 0.0
    realized_profit_eur: float = 0.0
    total_fees_eur: float = 0.0
    peak_equity_eur: float = 10_000.0
    max_drawdown: float = 0.0
    last_market_price_eur: float = 90_000.0
    trades: list[Trade] = field(default_factory=list)
    lots: list[PositionLot] = field(default_factory=list)
    cooldown_remaining: int = 0
    buy_cooldown_remaining: int = 0
    post_sale_cooldown_remaining: int = 0
    last_sale_price_eur: float = 0.0
    reentry_reference_eur: float = 0.0
    reentry_prices: list[float] = field(default_factory=list)
    bearish_confirmation_count: int = 0
    floor_prices: list[float] = field(default_factory=list)
    floor_reference_eur: float = 0.0
    rebound_peak_eur: float = 0.0
    consecutive_losses: int = 0
    loss_streak_cooldown_remaining: int = 0

    def now(self) -> datetime:
        """Reloj sustituible para que el replay conserve fechas históricas."""
        return getattr(self, "replay_time", None) or datetime.now()

    def equity(self, price_eur: float) -> float:
        return self.cash_eur + self.bitcoin * price_eur

    @property
    def average_cost_eur(self) -> float:
        return self.cost_basis_eur / self.bitcoin if self.bitcoin > 0 else 0.0

    def unrealized_profit(self, price_eur: float) -> float:
        return self.bitcoin * price_eur - self.cost_basis_eur

    @property
    def frozen_bitcoin(self) -> float:
        return sum(lot.bitcoin for lot in self.lots if lot.frozen)

    @property
    def tradable_bitcoin(self) -> float:
        return sum(lot.bitcoin for lot in self.lots if not lot.frozen)

    @property
    def tradable_cost_basis_eur(self) -> float:
        return sum(lot.cost_basis_eur for lot in self.lots if not lot.frozen)

    def position_return(self, price_eur: float) -> float:
        if self.cost_basis_eur <= 0:
            return 0.0
        return self.unrealized_profit(price_eur) / self.cost_basis_eur

    def freeze_existing_lots(self) -> None:
        for lot in self.lots:
            lot.frozen = True

    def profitable_sell_price(
        self,
        profit_rate: float,
        fee_rate: float = 0.0,
        slippage_rate: float = 0.0,
        tradable_only: bool = False,
    ) -> float:
        amount = self.tradable_bitcoin if tradable_only else self.bitcoin
        cost = self.tradable_cost_basis_eur if tradable_only else self.cost_basis_eur
        if amount <= 0:
            return 0.0
        net_factor = (1 - fee_rate) * (1 - slippage_rate)
        average = cost / amount
        target_profit = lot.target_profit_rate or profit_rate
        return average * (1 + target_profit) / net_factor

    def lot_target_price(
        self,
        lot: PositionLot,
        profit_rate: float,
        fee_rate: float = 0.0,
        slippage_rate: float = 0.0,
    ) -> float:
        net_factor = (1 - fee_rate) * (1 - slippage_rate)
        average = lot.cost_basis_eur / lot.bitcoin
        return average * (1 + profit_rate) / net_factor

    def profitable_lots(
        self,
        price_eur: float,
        profit_rate: float,
        fee_rate: float = 0.0,
        slippage_rate: float = 0.0,
        include_frozen: bool = True,
    ) -> list[PositionLot]:
        return [
            lot
            for lot in self.lots
            if (include_frozen or not lot.frozen)
            and price_eur
            >= self.lot_target_price(
                lot,
                profit_rate,
                fee_rate,
                slippage_rate,
            )
        ]

    def next_lot_target_price(
        self,
        profit_rate: float,
        fee_rate: float = 0.0,
        slippage_rate: float = 0.0,
        include_frozen: bool = True,
    ) -> float:
        candidates = [
            self.lot_target_price(lot, profit_rate, fee_rate, slippage_rate)
            for lot in self.lots
            if include_frozen or not lot.frozen
        ]
        return min(candidates) if candidates else 0.0

    def record_equity(self, price_eur: float) -> float:
        self.last_market_price_eur = price_eur
        equity = self.equity(price_eur)
        self.peak_equity_eur = max(self.peak_equity_eur, equity)
        drawdown = (
            (self.peak_equity_eur - equity) / self.peak_equity_eur
            if self.peak_equity_eur > 0
            else 0.0
        )
        self.max_drawdown = max(self.max_drawdown, drawdown)
        return drawdown

    def can_buy(self, price_eur: float, fee_rate: float = 0.0) -> bool:
        position_value = self.bitcoin * price_eur
        spendable_cash = self.cash_eur - self.minimum_cash_eur
        return (
            spendable_cash >= self.minimum_trade_eur * (1 + fee_rate)
            and position_value < self.equity(price_eur) * self.max_position_fraction
            and len(self.lots) < self.max_open_lots
        )

    def price_allows_next_buy(
        self,
        price_eur: float,
        minimum_drop: float,
    ) -> bool:
        """Escalona entradas: cada lote nuevo debe comprarse más barato."""
        if not self.lots or minimum_drop <= 0:
            return True
        latest_entry = self.lots[-1].entry_price_eur
        if latest_entry <= 0:
            latest_entry = self.lots[-1].cost_basis_eur / self.lots[-1].bitcoin
        return price_eur <= latest_entry * (1 - minimum_drop)

    def register_sale(self, price_eur: float, cooldown_ticks: int) -> None:
        self.last_sale_price_eur = price_eur
        self.reentry_reference_eur = price_eur
        self.post_sale_cooldown_remaining = cooldown_ticks
        self.reentry_prices.clear()

    def update_reentry_reference(
        self, price_eur: float, stable_ticks: int, stable_range: float
    ) -> None:
        if self.last_sale_price_eur <= 0:
            return
        self.reentry_prices.append(price_eur)
        self.reentry_prices = self.reentry_prices[-stable_ticks:]
        if len(self.reentry_prices) < stable_ticks:
            return
        ordered = sorted(self.reentry_prices)
        median = ordered[len(ordered) // 2]
        if (max(ordered) - min(ordered)) / median <= stable_range:
            self.reentry_reference_eur = max(
                self.reentry_reference_eur, median
            )

    def post_sale_buy_allowed(
        self, price_eur: float, pullback: float, technical_rebound: bool
    ) -> bool:
        if self.last_sale_price_eur <= 0:
            return True
        reference = self.reentry_reference_eur or self.last_sale_price_eur
        return (
            self.post_sale_cooldown_remaining == 0
            and price_eur <= reference * (1 - pullback)
            and technical_rebound
        )

    def losing_lots(self, price_eur: float, loss: float) -> list[PositionLot]:
        return [
            lot for lot in self.lots
            if price_eur <= (lot.entry_price_eur or lot.cost_basis_eur / lot.bitcoin)
            * (1 - loss)
        ]

    def update_defensive_exit(
        self,
        price_eur: float,
        bearish: bool,
        stable_ticks: int,
        stable_range: float,
        rebound: float,
    ) -> bool:
        self.bearish_confirmation_count = (
            self.bearish_confirmation_count + 1 if bearish else 0
        )
        if not self.lots:
            self.floor_prices.clear()
            self.floor_reference_eur = self.rebound_peak_eur = 0.0
            return False
        self.floor_prices.append(price_eur)
        self.floor_prices = self.floor_prices[-stable_ticks:]
        if len(self.floor_prices) == stable_ticks:
            ordered = sorted(self.floor_prices)
            median = ordered[len(ordered) // 2]
            if (max(ordered) - min(ordered)) / median <= stable_range:
                self.floor_reference_eur = median
                self.rebound_peak_eur = max(self.rebound_peak_eur, price_eur)
        if self.floor_reference_eur > 0:
            self.rebound_peak_eur = max(self.rebound_peak_eur, price_eur)
        return (
            bearish
            and self.floor_reference_eur > 0
            and self.rebound_peak_eur
            >= self.floor_reference_eur * (1 + rebound)
            and price_eur < self.rebound_peak_eur
        )

    def risk_sized_value(
        self,
        price_eur: float,
        risk_rate: float,
        stop_loss: float,
        fee_rate: float = 0.0,
        slippage_rate: float = 0.0,
    ) -> float:
        effective_loss = stop_loss + 2 * fee_rate + 2 * slippage_rate
        if effective_loss <= 0:
            return 0.0
        risk_budget = self.equity(price_eur) * risk_rate
        return risk_budget / effective_loss

    def estimated_open_risk(
        self,
        stop_loss: float,
        fee_rate: float = 0.0,
        slippage_rate: float = 0.0,
    ) -> float:
        total = 0.0
        for lot in self.lots:
            entry = lot.entry_price_eur or lot.cost_basis_eur / lot.bitcoin
            lot_stop_loss = lot.stop_loss_rate or stop_loss
            stop_market = entry * (1 - lot_stop_loss)
            expected_net = (
                lot.bitcoin
                * stop_market
                * (1 - slippage_rate)
                * (1 - fee_rate)
            )
            total += max(0.0, lot.cost_basis_eur - expected_net)
        return total

    def estimated_new_trade_risk(
        self,
        price_eur: float,
        total_budget_eur: float,
        stop_loss: float,
        fee_rate: float = 0.0,
        slippage_rate: float = 0.0,
    ) -> float:
        principal = total_budget_eur / (1 + fee_rate)
        execution_price = price_eur * (1 + slippage_rate)
        amount = principal / execution_price
        stop_market = execution_price * (1 - stop_loss)
        expected_net = (
            amount
            * stop_market
            * (1 - slippage_rate)
            * (1 - fee_rate)
        )
        return max(0.0, total_budget_eur - expected_net)

    def can_add_risk(
        self,
        price_eur: float,
        total_budget_eur: float,
        stop_loss: float,
        maximum_risk_eur: float,
        fee_rate: float = 0.0,
        slippage_rate: float = 0.0,
    ) -> bool:
        projected = self.estimated_open_risk(
            stop_loss, fee_rate, slippage_rate
        ) + self.estimated_new_trade_risk(
            price_eur,
            total_budget_eur,
            stop_loss,
            fee_rate,
            slippage_rate,
        )
        return projected <= maximum_risk_eur

    def record_sale_result(
        self,
        pnl_eur: float,
        pause_after: int,
        pause_ticks: int,
    ) -> None:
        if pnl_eur < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= pause_after:
                self.loss_streak_cooldown_remaining = pause_ticks
        else:
            self.consecutive_losses = 0
            self.loss_streak_cooldown_remaining = 0

    def fixed_initial_buy_value(
        self,
        fraction: float,
        fee_rate: float = 0.0,
    ) -> float:
        """Principal cuya salida total, incluida comisión, es fija."""
        if not 0 < fraction <= 1:
            raise ValueError("Porcentaje de compra no válido.")
        return self.initial_cash_eur * fraction / (1 + fee_rate)

    def buy(
        self,
        price_eur: float,
        value_eur: float,
        reason: str,
        max_fraction: float | None = None,
        fee_rate: float = 0.0,
        slippage_rate: float = 0.0,
        recovery_lot: bool = False,
        stop_loss_rate: float = 0.0,
        target_profit_rate: float = 0.0,
        trailing_activation_rate: float = 0.0,
        trailing_distance_rate: float = 0.0,
    ) -> Trade:
        if price_eur <= 0:
            raise ValueError("El precio debe ser positivo.")
        if len(self.lots) >= self.max_open_lots:
            raise ValueError(
                f"Ya hay {self.max_open_lots} lotes abiertos, el máximo permitido."
            )
        fraction = self.max_buy_fraction if max_fraction is None else max_fraction
        if not 0 < fraction <= self.max_position_fraction:
            raise ValueError("Porcentaje de compra no válido.")
        equity = self.equity(price_eur)
        remaining_exposure = max(
            0.0,
            equity * self.max_position_fraction - self.bitcoin * price_eur,
        )
        spendable_cash = max(0.0, self.cash_eur - self.minimum_cash_eur)
        maximum = min(equity * fraction, remaining_exposure, spendable_cash)
        value_eur = min(value_eur, maximum / (1 + fee_rate))
        if value_eur < self.minimum_trade_eur or value_eur > self.cash_eur:
            raise ValueError(
                f"La compra mínima es de {self.minimum_trade_eur:,.0f} € "
                f"y deben conservarse {self.minimum_cash_eur:,.0f} €."
            )

        execution_price = price_eur * (1 + slippage_rate)
        fee = value_eur * fee_rate
        amount = value_eur / execution_price
        total_cost = value_eur + fee
        self.cash_eur -= total_cost
        self.bitcoin += amount
        self.cost_basis_eur += total_cost
        self.lots.append(
            PositionLot(
                amount,
                total_cost,
                timestamp=self.now(),
                frozen=False,
                entry_price_eur=execution_price,
                peak_price_eur=execution_price,
                stop_loss_rate=stop_loss_rate,
                target_profit_rate=target_profit_rate,
                trailing_activation_rate=trailing_activation_rate,
                trailing_distance_rate=trailing_distance_rate,
            )
        )
        self.total_fees_eur += fee
        trade = Trade(
            self.now(),
            "COMPRA",
            amount,
            execution_price,
            value_eur,
            reason,
            fee,
        )
        self.trades.append(trade)
        return trade

    def sell_all(
        self,
        price_eur: float,
        reason: str,
        fee_rate: float = 0.0,
        slippage_rate: float = 0.0,
    ) -> Trade:
        return self._sell_lots(
            price_eur,
            reason,
            fee_rate,
            slippage_rate,
            tradable_only=False,
        )

    def sell_tradable(
        self,
        price_eur: float,
        reason: str,
        fee_rate: float = 0.0,
        slippage_rate: float = 0.0,
    ) -> Trade:
        return self._sell_lots(
            price_eur,
            reason,
            fee_rate,
            slippage_rate,
            tradable_only=True,
        )

    def sell_profitable_lots(
        self,
        price_eur: float,
        profit_rate: float,
        reason: str,
        fee_rate: float = 0.0,
        slippage_rate: float = 0.0,
        include_frozen: bool = True,
    ) -> Trade:
        selected = self.profitable_lots(
            price_eur,
            profit_rate,
            fee_rate,
            slippage_rate,
            include_frozen,
        )
        if not selected:
            raise ValueError("Ningún lote ha alcanzado su objetivo rentable.")
        return self._execute_lot_sale(
            selected,
            price_eur,
            reason,
            fee_rate,
            slippage_rate,
        )

    def sell_selected_lots(
        self,
        lots: list[PositionLot],
        price_eur: float,
        reason: str,
        fee_rate: float = 0.0,
        slippage_rate: float = 0.0,
    ) -> Trade:
        if not lots:
            raise ValueError("No hay lotes seleccionados para vender.")
        return self._execute_lot_sale(
            lots, price_eur, reason, fee_rate, slippage_rate
        )

    def stopped_lots(
        self,
        price_eur: float,
        stop_loss: float,
        trailing_activation: float,
        trailing_distance: float,
    ) -> tuple[list[PositionLot], str]:
        stopped: list[PositionLot] = []
        trailing_triggered = False
        for lot in self.lots:
            entry = lot.entry_price_eur or lot.cost_basis_eur / lot.bitcoin
            lot.peak_price_eur = max(lot.peak_price_eur or entry, price_eur)
            lot_stop_loss = lot.stop_loss_rate or stop_loss
            lot_trailing_activation = (
                lot.trailing_activation_rate or trailing_activation
            )
            lot_trailing_distance = lot.trailing_distance_rate or trailing_distance
            stop = entry * (1 - lot_stop_loss)
            trailing_active = lot.peak_price_eur >= entry * (
                1 + lot_trailing_activation
            )
            if trailing_active:
                stop = max(
                    stop, lot.peak_price_eur * (1 - lot_trailing_distance)
                )
            if price_eur <= stop:
                stopped.append(lot)
                trailing_triggered = trailing_triggered or trailing_active
        return stopped, "Trailing stop" if trailing_triggered else "Stop-loss"

    def next_stop_price(
        self,
        stop_loss: float,
        trailing_activation: float,
        trailing_distance: float,
    ) -> float:
        stops = []
        for lot in self.lots:
            entry = lot.entry_price_eur or lot.cost_basis_eur / lot.bitcoin
            lot_stop_loss = lot.stop_loss_rate or stop_loss
            lot_trailing_activation = (
                lot.trailing_activation_rate or trailing_activation
            )
            lot_trailing_distance = lot.trailing_distance_rate or trailing_distance
            stop = entry * (1 - lot_stop_loss)
            peak = lot.peak_price_eur or entry
            if peak >= entry * (1 + lot_trailing_activation):
                stop = max(stop, peak * (1 - lot_trailing_distance))
            stops.append(stop)
        return max(stops) if stops else 0.0

    def realized_loss_since(self, since: datetime) -> float:
        return -sum(
            min(trade.pnl_eur, 0.0)
            for trade in self.trades
            if trade.side == "VENTA" and trade.timestamp >= since
        )

    def _sell_lots(
        self,
        price_eur: float,
        reason: str,
        fee_rate: float,
        slippage_rate: float,
        tradable_only: bool,
    ) -> Trade:
        if price_eur <= 0:
            raise ValueError("El precio debe ser positivo.")
        selected = (
            [lot for lot in self.lots if not lot.frozen]
            if tradable_only
            else list(self.lots)
        )
        if not selected and self.bitcoin > 0 and not self.lots:
            selected = [PositionLot(self.bitcoin, self.cost_basis_eur)]
        amount = sum(lot.bitcoin for lot in selected)
        selected_cost = sum(lot.cost_basis_eur for lot in selected)
        if amount <= 0:
            raise ValueError("No hay Bitcoin para vender.")

        return self._execute_lot_sale(
            selected,
            price_eur,
            reason,
            fee_rate,
            slippage_rate,
        )

    def _execute_lot_sale(
        self,
        selected: list[PositionLot],
        price_eur: float,
        reason: str,
        fee_rate: float,
        slippage_rate: float,
    ) -> Trade:
        amount = sum(lot.bitcoin for lot in selected)
        selected_cost = sum(lot.cost_basis_eur for lot in selected)

        execution_price = price_eur * (1 - slippage_rate)
        value_eur = amount * execution_price
        fee = value_eur * fee_rate
        net_value = value_eur - fee
        profit = net_value - selected_cost
        self.cash_eur += net_value
        self.bitcoin -= amount
        self.cost_basis_eur -= selected_cost
        selected_ids = {id(lot) for lot in selected}
        self.lots = [lot for lot in self.lots if id(lot) not in selected_ids]
        if self.bitcoin < 1e-12:
            self.bitcoin = 0.0
            self.cost_basis_eur = 0.0
        self.realized_profit_eur += profit
        self.total_fees_eur += fee
        trade = Trade(
            self.now(),
            "VENTA",
            amount,
            execution_price,
            value_eur,
            reason,
            fee,
            profit,
        )
        self.trades.append(trade)
        return trade


class PriceSimulator:
    def __init__(
        self,
        initial_price: float = 90_000.0,
        seed: int | None = None,
        anchor_price: float = 90_000.0,
        minimum_price: float = 20_000.0,
        maximum_price: float = 200_000.0,
    ):
        self.anchor_price = anchor_price
        self.minimum_price = minimum_price
        self.maximum_price = maximum_price
        self.price = min(max(initial_price, minimum_price), maximum_price)
        self._random = random.Random(seed)

    def tick(self) -> float:
        distance = (self.anchor_price - self.price) / self.anchor_price
        mean_reversion = distance * 0.0008
        market_noise = self._random.gauss(0.0, 0.0015)
        self.price *= 1 + mean_reversion + market_noise
        self.price = min(
            max(self.price, self.minimum_price),
            self.maximum_price,
        )
        return self.price


class MovingAverageStrategy:
    """Estrategia contraria: compra debilidad y vende fortaleza."""

    def __init__(
        self,
        short_window: int = 5,
        long_window: int = 15,
        threshold: float = 0.002,
    ):
        if short_window >= long_window:
            raise ValueError("La media corta debe ser menor que la larga.")
        self.short_window = short_window
        self.long_window = long_window
        self.threshold = threshold

    def signal(self, prices: list[float]) -> str:
        if len(prices) < self.long_window:
            return "ESPERAR"
        short = sum(prices[-self.short_window :]) / self.short_window
        long = sum(prices[-self.long_window :]) / self.long_window
        if short < long * (1 - self.threshold):
            return "COMPRAR"
        if short > long * (1 + self.threshold):
            return "VENDER"
        return "ESPERAR"


class RecoveryController:
    """Separa una posición antigua en pérdidas de los nuevos lotes operables."""

    def __init__(
        self,
        loss_trigger: float = 0.10,
        stable_ticks: int = 15,
        stable_range: float = 0.01,
    ):
        self.loss_trigger = loss_trigger
        self.stable_ticks = stable_ticks
        self.stable_range = stable_range
        self.active = False
        self.enabled = False
        self.prices: list[float] = []

    def update(self, account: PaperAccount, price: float) -> str:
        if not self.active and account.position_return(price) <= -self.loss_trigger:
            account.freeze_existing_lots()
            self.active = True
            self.enabled = False
            self.prices = []

        if not self.active:
            return "Modo normal"

        self.prices.append(price)
        self.prices = self.prices[-self.stable_ticks :]
        if len(self.prices) < self.stable_ticks:
            return (
                f"Caída profunda: estabilización "
                f"{len(self.prices)}/{self.stable_ticks}"
            )

        midpoint = sum(self.prices) / len(self.prices)
        width = (max(self.prices) - min(self.prices)) / midpoint
        if width <= self.stable_range:
            self.enabled = True

        if self.enabled:
            return (
                f"Recuperación activa · rango {width:.2%} · "
                f"{account.frozen_bitcoin:.6f} BTC congelado"
            )
        return (
            f"Esperando estabilidad · rango {width:.2%}/"
            f"{self.stable_range:.2%}"
        )


class TrendConfirmation:
    """Arma una referencia tras tres movimientos y opera al mejorarla."""

    def __init__(
        self,
        confirmation_ticks: int = 3,
        sell_gain: float = 0.025,
        reference_expiry_ticks: int = 300,
    ):
        if confirmation_ticks < 1:
            raise ValueError("La confirmación debe ser de al menos un ciclo.")
        if sell_gain <= 0:
            raise ValueError("El objetivo de venta debe ser positivo.")
        if reference_expiry_ticks < confirmation_ticks:
            raise ValueError("La caducidad debe superar los ciclos de confirmación.")
        self.confirmation_ticks = confirmation_ticks
        self.sell_gain = sell_gain
        self.reference_expiry_ticks = reference_expiry_ticks
        self.phase = "ESPERANDO"
        self.reference_price: float | None = None
        self.last_price: float | None = None
        self.up_ticks = 0
        self.down_ticks = 0
        self.phase_age = 0

    def reset(self) -> None:
        self.phase = "ESPERANDO"
        self.reference_price = None
        self.up_ticks = 0
        self.down_ticks = 0
        self.phase_age = 0

    def _arm(self, phase: str, price: float) -> None:
        self.phase = phase
        self.reference_price = price
        self.phase_age = 0
        self.up_ticks = 0
        self.down_ticks = 0

    def update(
        self,
        price: float,
        has_bitcoin: bool,
        minimum_sell_price: float = 0.0,
    ) -> tuple[str, str]:
        if self.last_price is None:
            self.last_price = price
            return "ESPERAR", "Recogiendo precios"

        if price > self.last_price:
            self.up_ticks += 1
            self.down_ticks = 0
        elif price < self.last_price:
            self.down_ticks += 1
            self.up_ticks = 0

        if self.phase != "ESPERANDO":
            self.phase_age += 1
            if self.phase_age >= self.reference_expiry_ticks:
                self.reset()
                self.last_price = price
                return "ESPERAR", "Referencia caducada: buscando una nueva tendencia"

        if self.phase == "ESPERANDO":
            if self.down_ticks >= self.confirmation_ticks:
                self._arm("COMPRA_ARMADA", price)
            elif self.up_ticks >= self.confirmation_ticks and has_bitcoin:
                self._arm("VENTA_ARMADA", price)

        elif self.phase == "COMPRA_ARMADA":
            if price < float(self.reference_price):
                reference = self.reference_price
                self.reset()
                self.last_price = price
                return "COMPRAR", f"Precio inferior a referencia ({reference:,.2f} €)"
            if self.up_ticks >= self.confirmation_ticks:
                if has_bitcoin:
                    self._arm("VENTA_ARMADA", price)
                    self.last_price = price
                    return (
                        "ESPERAR",
                        "Tendencia invertida: venta preparada con nueva referencia",
                    )
                self.reset()
                self.last_price = price
                return "ESPERAR", "Subida detectada: compra preparada cancelada"

        elif self.phase == "VENTA_ARMADA":
            target = max(
                float(self.reference_price) * (1 + self.sell_gain),
                minimum_sell_price,
            )
            if price >= target:
                reference = self.reference_price
                self.reset()
                self.last_price = price
                return "VENDER", (
                    f"Objetivo +{self.sell_gain:.1%} alcanzado "
                    f"(referencia {reference:,.2f} €)"
                )
            if self.down_ticks >= self.confirmation_ticks:
                self._arm("COMPRA_ARMADA", price)
                self.last_price = price
                return (
                    "ESPERAR",
                    "Tendencia invertida: compra preparada con nueva referencia",
                )

        self.last_price = price
        if self.phase == "COMPRA_ARMADA":
            remaining = self.reference_expiry_ticks - self.phase_age
            status = (
                f"Compra preparada · referencia {self.reference_price:,.2f} € "
                f"· caduca en {remaining} s"
            )
        elif self.phase == "VENTA_ARMADA":
            target = max(
                float(self.reference_price) * (1 + self.sell_gain),
                minimum_sell_price,
            )
            status = (
                f"Venta preparada · referencia {self.reference_price:,.2f} € "
                f"· objetivo {target:,.2f} € (+{self.sell_gain:.1%}) "
                f"· caduca en {self.reference_expiry_ticks - self.phase_age} s"
            )
        else:
            status = (
                f"Buscando tendencia · ↓ {self.down_ticks}/"
                f"{self.confirmation_ticks} · ↑ {self.up_ticks}/"
                f"{self.confirmation_ticks}"
            )
        return "ESPERAR", status
