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


@dataclass
class PaperAccount:
    initial_cash_eur: float = 10_000.0
    cash_eur: float = 10_000.0
    bitcoin: float = 0.0
    max_buy_fraction: float = 0.20
    max_position_fraction: float = 0.80
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
        return average * (1 + profit_rate) / net_factor

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
        )

    def buy(
        self,
        price_eur: float,
        value_eur: float,
        reason: str,
        max_fraction: float | None = None,
        fee_rate: float = 0.0,
        slippage_rate: float = 0.0,
        recovery_lot: bool = False,
    ) -> Trade:
        if price_eur <= 0:
            raise ValueError("El precio debe ser positivo.")
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
        self.lots.append(PositionLot(amount, total_cost, frozen=False))
        self.total_fees_eur += fee
        trade = Trade(
            datetime.now(),
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
            datetime.now(),
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
