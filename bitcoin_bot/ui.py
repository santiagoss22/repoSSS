from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import os
import subprocess
import sys
import time

from PySide6.QtCore import QStandardPaths, QTimer, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bitcoin_bot.backtest import download_coinbase_daily_prices, run_backtest
from bitcoin_bot.config import BotSettings
from bitcoin_bot.market_data import Candle, LiveMarketWorker
from bitcoin_bot.persistence import load_state, save_state
from bitcoin_bot.simulator import (
    PaperAccount,
    PriceSimulator,
)
from bitcoin_bot.technical_strategy import MultiIndicatorStrategy


class KeepAwakeManager:
    """Evita el reposo inactivo del Mac mientras el bot está activado."""

    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None

    @property
    def active(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> bool:
        if self.active:
            return True
        executable = Path("/usr/bin/caffeinate")
        if not executable.exists():
            return False
        self.process = subprocess.Popen(
            [str(executable), "-i", "-w", str(os.getpid())],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return self.active

    def stop(self) -> None:
        if self.active:
            self.process.terminate()
        self.process = None


class MetricCard(QFrame):
    def __init__(self, title: str, accent: str = "#94a3b8") -> None:
        super().__init__()
        self.setObjectName("metricCard")
        self.title_label = QLabel(title.upper())
        self.title_label.setObjectName("cardTitle")
        self.value_label = QLabel("—")
        self.value_label.setObjectName("cardValue")
        self.value_label.setStyleSheet(f"color: {accent};")
        self.detail_label = QLabel("")
        self.detail_label.setObjectName("cardDetail")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 13, 15, 13)
        layout.setSpacing(4)
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label)

    def set_value(self, value: str, detail: str = "") -> None:
        self.value_label.setText(value)
        self.detail_label.setText(detail)


class PriceChart(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.prices: list[float] = []
        self.trades = []
        self.purchase_levels: list[tuple[float, bool]] = []
        self.risk_levels: tuple[float, float] = (0.0, 0.0)
        self.setMinimumHeight(210)

    def set_data(
        self, prices: list[float], trades: list, lots: list,
        risk_levels: tuple[float, float] = (0.0, 0.0),
    ) -> None:
        self.prices = prices[-120:]
        # Las compras se dibujan desde los lotes abiertos, no desde el historial.
        # Así desaparecen del gráfico en cuanto se vende el lote correspondiente.
        self.trades = [trade for trade in trades if trade.side == "VENTA"][-40:]
        self.purchase_levels = [
            (lot.cost_basis_eur / lot.bitcoin, lot.frozen)
            for lot in lots
            if lot.bitcoin > 0
        ][-8:]
        self.risk_levels = risk_levels
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0f172a"))
        painter.setPen(QPen(QColor("#1e293b"), 1))
        for division in range(1, 5):
            y = int(self.height() * division / 5)
            painter.drawLine(12, y, self.width() - 12, y)
        if len(self.prices) < 2:
            return
        low, high = min(self.prices), max(self.prices)
        spread = max(high - low, 1.0)
        left, right = 132, 12
        width = max(self.width() - left - right, 1)
        height = max(self.height() - 24, 1)
        points = [
            (
                left + index * width / (len(self.prices) - 1),
                12 + (high - price) * height / spread,
            )
            for index, price in enumerate(self.prices)
        ]
        path = QPainterPath()
        path.moveTo(points[0][0], points[0][1])
        for point in points[1:]:
            path.lineTo(point[0], point[1])
        area = QPainterPath(path)
        area.lineTo(points[-1][0], self.height() - 12)
        area.lineTo(points[0][0], self.height() - 12)
        area.closeSubpath()
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0, QColor(245, 158, 11, 90))
        gradient.setColorAt(1, QColor(245, 158, 11, 3))
        painter.fillPath(area, gradient)
        painter.setPen(QPen(QColor("#f59e0b"), 2))
        painter.drawPath(path)
        self._draw_purchase_levels(painter, low, high, height, left)
        self._draw_risk_levels(painter, low, high, height, left)
        # Sitúa cada operación en el punto visible cuyo precio más se aproxima
        # al precio ejecutado. Esto mantiene el gráfico útil tras reiniciar.
        used: set[tuple[int, str]] = set()
        for trade in self.trades:
            index = min(
                range(len(self.prices)),
                key=lambda item: abs(self.prices[item] - trade.price_eur),
            )
            key = (index, trade.side)
            if key in used:
                continue
            used.add(key)
            x, y = points[index]
            color = QColor("#22c55e" if trade.side == "COMPRA" else "#ef4444")
            painter.setBrush(color)
            painter.setPen(QPen(QColor("#f8fafc"), 1))
            painter.drawEllipse(int(x) - 5, int(y) - 5, 10, 10)
            painter.setPen(QPen(color, 1))
            label = "C" if trade.side == "COMPRA" else "V"
            painter.drawText(int(x) + 7, int(y) - 7, label)
        self._draw_active_purchase_points(painter, points)

    def _draw_active_purchase_points(
        self, painter: QPainter, points: list[tuple[float, float]]
    ) -> None:
        used: set[int] = set()
        for level, _ in self.purchase_levels:
            index = min(
                range(len(self.prices)),
                key=lambda item: abs(self.prices[item] - level),
            )
            if index in used:
                continue
            used.add(index)
            x, y = points[index]
            color = QColor("#22c55e")
            painter.setBrush(color)
            painter.setPen(QPen(QColor("#f8fafc"), 1))
            painter.drawEllipse(int(x) - 5, int(y) - 5, 10, 10)
            painter.setPen(QPen(color, 1))
            painter.drawText(int(x) + 7, int(y) - 7, "C")

    def _draw_purchase_levels(
        self, painter: QPainter, low: float, high: float, height: float, left: int
    ) -> None:
        if not self.purchase_levels:
            return
        spread = max(high - low, 1.0)
        current = self.prices[-1]
        occupied: list[float] = []
        for level, frozen in self.purchase_levels:
            raw_y = 12 + (high - level) * height / spread
            top, bottom, separation = 14, self.height() - 14, 17
            preferred = min(max(raw_y, top), bottom)
            candidates = [preferred]
            candidates.extend(
                float(position)
                for position in range(top, max(top, bottom) + 1, separation)
            )
            available = [
                candidate
                for candidate in candidates
                if all(
                    abs(candidate - previous) >= separation
                    for previous in occupied
                )
            ]
            if not available:
                # No hay espacio para otra etiqueta legible. La línea del lote
                # sigue dibujada, pero se evita solapar texto o bloquear el pintado.
                continue
            y = min(available, key=lambda candidate: abs(candidate - preferred))
            occupied.append(y)
            difference = (current / level - 1) * 100
            arrow = "↑" if raw_y < 14 else "↓" if raw_y > self.height() - 14 else ""
            color = QColor("#14b8a6" if frozen else "#22c55e")
            painter.setPen(QPen(color, 1, Qt.DashLine))
            painter.drawLine(left - 10, int(y), self.width() - 12, int(y))
            painter.setPen(QPen(color, 1))
            state = "◆" if frozen else "C"
            text = f"{arrow}{state} {level:,.0f} €  {difference:+.1f}%"
            painter.drawText(8, int(y) + 4, text)

    def _draw_risk_levels(
        self, painter: QPainter, low: float, high: float, height: float, left: int
    ) -> None:
        spread = max(high - low, 1.0)
        for level, label, color_name in (
            (self.risk_levels[0], "STOP", "#ef4444"),
            (self.risk_levels[1], "OBJ", "#a78bfa"),
        ):
            if level <= 0:
                continue
            raw_y = 12 + (high - level) * height / spread
            y = min(max(raw_y, 14), self.height() - 14)
            color = QColor(color_name)
            painter.setPen(QPen(color, 1, Qt.DotLine))
            painter.drawLine(left, int(y), self.width() - 12, int(y))
            painter.setPen(QPen(color, 1))
            painter.drawText(self.width() - 112, int(y) - 4, f"{label} {level:,.0f} €")


class SettingsDialog(QDialog):
    def __init__(self, settings: BotSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configuración del bot")
        self.inputs: dict[str, QDoubleSpinBox | QSpinBox] = {}
        form = QFormLayout(self)

        def percentage(name: str, label: str, value: float, maximum: float = 100):
            field = QDoubleSpinBox()
            field.setRange(0.01, maximum)
            field.setDecimals(2)
            field.setSuffix(" %")
            field.setValue(value * 100)
            form.addRow(label, field)
            self.inputs[name] = field

        percentage("risk_per_trade", "Riesgo por operación", settings.risk_per_trade, 5)
        percentage("stop_loss", "Stop-loss", settings.stop_loss, 30)
        percentage("sell_gain", "Take-profit", settings.sell_gain, 50)
        percentage(
            "trailing_activation", "Activar trailing desde",
            settings.trailing_activation, 50
        )
        percentage(
            "trailing_distance", "Distancia del trailing",
            settings.trailing_distance, 30
        )
        percentage("daily_loss_limit", "Límite diario", settings.daily_loss_limit, 20)
        percentage("weekly_loss_limit", "Límite semanal", settings.weekly_loss_limit, 40)
        percentage(
            "max_position_fraction", "Exposición máxima",
            settings.max_position_fraction, 100
        )
        percentage("max_spread", "Spread máximo", settings.max_spread, 5)
        percentage(
            "fee_rate",
            "Comisión por operación",
            settings.fee_rate,
            maximum=10,
        )
        percentage(
            "slippage_rate",
            "Deslizamiento estimado",
            settings.slippage_rate,
            maximum=10,
        )

        reserve = QDoubleSpinBox()
        reserve.setRange(0, 1_000_000)
        reserve.setSuffix(" €")
        reserve.setValue(settings.minimum_cash_eur)
        form.addRow("Reserva mínima", reserve)
        self.inputs["minimum_cash_eur"] = reserve

        minimum_trade = QDoubleSpinBox()
        minimum_trade.setRange(10, 100_000)
        minimum_trade.setSuffix(" €")
        minimum_trade.setValue(settings.minimum_trade_eur)
        form.addRow("Compra mínima", minimum_trade)
        self.inputs["minimum_trade_eur"] = minimum_trade

        cooldown = QSpinBox()
        cooldown.setRange(0, 600)
        cooldown.setValue(settings.cooldown_ticks)
        form.addRow("Cooldown tras pérdida (ciclos)", cooldown)
        self.inputs["cooldown_ticks"] = cooldown

        buy_spacing = QSpinBox()
        buy_spacing.setRange(0, 60)
        buy_spacing.setValue(settings.buy_spacing_ticks)
        form.addRow("Separación entre compras (ciclos)", buy_spacing)
        self.inputs["buy_spacing_ticks"] = buy_spacing

        buy_drop = QDoubleSpinBox()
        buy_drop.setRange(0, 10)
        buy_drop.setDecimals(2)
        buy_drop.setSingleStep(0.10)
        buy_drop.setSuffix(" %")
        buy_drop.setValue(settings.minimum_buy_price_drop * 100)
        form.addRow("Caída mínima para recomprar", buy_drop)
        self.inputs["minimum_buy_price_drop"] = buy_drop

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def apply_to(self, settings: BotSettings) -> None:
        settings.sell_gain = self.inputs["sell_gain"].value() / 100
        settings.fee_rate = self.inputs["fee_rate"].value() / 100
        settings.slippage_rate = self.inputs["slippage_rate"].value() / 100
        for name in (
            "risk_per_trade", "stop_loss", "trailing_activation",
            "trailing_distance", "daily_loss_limit", "weekly_loss_limit",
            "max_position_fraction",
            "max_spread",
        ):
            setattr(settings, name, self.inputs[name].value() / 100)
        settings.minimum_cash_eur = self.inputs["minimum_cash_eur"].value()
        settings.minimum_trade_eur = self.inputs["minimum_trade_eur"].value()
        settings.cooldown_ticks = int(self.inputs["cooldown_ticks"].value())
        settings.buy_spacing_ticks = int(
            self.inputs["buy_spacing_ticks"].value()
        )
        settings.minimum_buy_price_drop = (
            self.inputs["minimum_buy_price_drop"].value() / 100
        )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Bitcoin Paper Bot · 1 Lote")
        self.resize(1050, 760)
        data_dir = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
        self.data_dir = data_dir
        self.state_path = data_dir / "paper_bot_state.json"
        reset_marker = data_dir / "reset_on_next_launch"
        try:
            self.account, self.settings = load_state(self.state_path)
        except (OSError, ValueError, TypeError):
            self.account, self.settings = PaperAccount(), BotSettings()
        if reset_marker.exists():
            self.account = PaperAccount()
            try:
                reset_marker.unlink()
                save_state(self.state_path, self.account, self.settings)
            except OSError:
                pass

        self.account.minimum_cash_eur = self.settings.minimum_cash_eur
        self.account.minimum_trade_eur = self.settings.minimum_trade_eur
        self.account.max_position_fraction = self.settings.max_position_fraction
        self.account.max_open_lots = self.settings.max_open_lots
        for lot in self.account.lots:
            lot.frozen = False
        self.market = PriceSimulator(initial_price=self.account.last_market_price_eur)
        self.strategy = MultiIndicatorStrategy()
        self.current_size_factor = 1.0
        self.keep_awake = KeepAwakeManager()
        self.prices = [self.market.price]
        self.market_worker: LiveMarketWorker | None = None
        self.market_mode = "simulated"
        self.live_histories: dict[str, list[Candle]] = {}
        self.live_signal_pending = False
        self.last_live_update = 0.0
        self.live_bid = 0.0
        self.live_ask = 0.0
        self.live_volume_1h = 0.0

        self.brand_icon = QLabel("₿")
        self.brand_icon.setObjectName("brandIcon")
        self.brand_title = QLabel("BITCOIN PAPER BOT · 1 LOTE")
        self.brand_title.setObjectName("brandTitle")
        self.brand_subtitle = QLabel(
            "Simulación independiente · Un único lote · Sin dinero real"
        )
        self.brand_subtitle.setObjectName("brandSubtitle")
        self.price_label = QLabel()
        self.price_label.setObjectName("price")
        self.signal_label = QLabel("● ESPERAR")
        self.signal_label.setObjectName("signalBadge")
        self.signal_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.source_combo = QComboBox()
        self.source_combo.addItem("Mercado simulado", "simulated")
        self.source_combo.addItem("Binance · BTC/EUR", "binance")
        self.source_combo.addItem("Coinbase · BTC/EUR", "coinbase")
        self.timeframe_combo = QComboBox()
        for timeframe in ("5m", "1h", "1d"):
            self.timeframe_combo.addItem(timeframe, timeframe)
        self.timeframe_combo.setCurrentText("1h")
        self.timeframe_combo.setEnabled(False)
        self.connection_label = QLabel("● Simulación local")
        self.connection_label.setObjectName("connectionStatus")
        self.bot_status_label = QLabel("Bot: esperando tendencia")
        self.bot_status_label.setObjectName("botStatus")
        self.risk_status_label = QLabel("Riesgo: sin posiciones abiertas")
        self.risk_status_label.setObjectName("riskStatus")
        self.power_status_label = QLabel(
            "Energía: comportamiento normal del Mac"
        )
        self.power_status_label.setObjectName("powerStatus")
        self.decision_label = QLabel(
            "Decisión actual: esperando suficientes datos para evaluar el mercado."
        )
        self.decision_label.setObjectName("decisionStatus")
        self.decision_label.setWordWrap(True)
        self.bot_toggle = QCheckBox("Bot automático")
        self.bot_toggle.setObjectName("botToggle")

        self.buy_button = QPushButton("Comprar todo salvo 2.000 €")
        self.buy_button.setObjectName("buyButton")
        self.buy_half_button = QPushButton("Comprar (50 %)")
        self.buy_half_button.setObjectName("buyButton")
        self.sell_button = QPushButton("Vender todo")
        self.sell_button.setObjectName("sellButton")
        self.settings_button = QPushButton("⚙ Configuración")
        self.reset_button = QPushButton("↺ Reiniciar simulación")
        self.reset_button.setObjectName("resetButton")
        self.backtest_button = QPushButton("↗ Backtest histórico")
        self.chart = PriceChart()
        self.drawdown_bar = QProgressBar()
        self.drawdown_bar.setRange(0, 1000)
        self.drawdown_bar.setTextVisible(True)
        self.drawdown_bar.setObjectName("riskBar")
        self.cards = {
            "cash": MetricCard("Efectivo disponible", "#60a5fa"),
            "bitcoin": MetricCard("Posición Bitcoin", "#fbbf24"),
            "equity": MetricCard("Patrimonio total", "#a78bfa"),
            "profit": MetricCard("Resultado total", "#34d399"),
        }
        self.table = QTableWidget(0, 7)
        self.table.setAlternatingRowColors(True)
        self.table.setHorizontalHeaderLabels(
            ["Hora", "Acción", "BTC", "Precio", "Comisión", "Resultado", "Motivo"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)

        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        brand_text.addWidget(self.brand_title)
        brand_text.addWidget(self.brand_subtitle)
        header = QHBoxLayout()
        header.addWidget(self.brand_icon)
        header.addLayout(brand_text)
        header.addStretch()
        header.addWidget(self.reset_button)
        header.addWidget(self.settings_button)
        header.addWidget(self.backtest_button)

        market_header = QHBoxLayout()
        market_header.addWidget(self.price_label)
        market_header.addStretch()
        market_header.addWidget(self.connection_label)
        market_header.addWidget(self.source_combo)
        market_header.addWidget(self.timeframe_combo)
        market_header.addWidget(self.signal_label)

        controls = QHBoxLayout()
        controls.addWidget(self.bot_toggle)
        controls.addStretch()
        controls.addWidget(self.buy_button)
        controls.addWidget(self.sell_button)

        metrics_grid = QGridLayout()
        metrics_grid.setSpacing(10)
        for index, card in enumerate(self.cards.values()):
            metrics_grid.addWidget(card, index // 4, index % 4)

        chart_panel = QFrame()
        chart_panel.setObjectName("panel")
        chart_layout = QVBoxLayout(chart_panel)
        chart_layout.setContentsMargins(14, 12, 14, 12)
        chart_title = QLabel("EVOLUCIÓN SIMULADA DE BTC")
        chart_title.setObjectName("sectionTitle")
        chart_layout.addWidget(chart_title)
        chart_layout.addWidget(self.chart)

        risk_panel = QFrame()
        risk_panel.setObjectName("panel")
        risk_layout = QVBoxLayout(risk_panel)
        risk_title = QLabel("RIESGO Y AUTOMATIZACIÓN")
        risk_title.setObjectName("sectionTitle")
        risk_layout.addWidget(risk_title)
        risk_layout.addWidget(self.bot_status_label)
        risk_layout.addWidget(self.risk_status_label)
        risk_layout.addWidget(self.power_status_label)
        risk_layout.addWidget(self.decision_label)
        risk_layout.addWidget(self.drawdown_bar)
        risk_layout.addLayout(controls)

        dashboard = QWidget()
        dashboard_layout = QVBoxLayout(dashboard)
        dashboard_layout.setContentsMargins(0, 12, 0, 0)
        dashboard_layout.setSpacing(10)
        dashboard_layout.addLayout(market_header)
        dashboard_layout.addLayout(metrics_grid)
        dashboard_layout.addWidget(chart_panel)
        dashboard_layout.addWidget(risk_panel)

        history = QWidget()
        history_layout = QVBoxLayout(history)
        history_layout.setContentsMargins(0, 12, 0, 0)
        history_title = QLabel("HISTORIAL DE OPERACIONES SIMULADAS")
        history_title.setObjectName("sectionTitle")
        history_layout.addWidget(history_title)
        history_layout.addWidget(self.table)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(dashboard, "  Panel  ")
        self.tabs.addTab(history, "  Operaciones  ")

        layout = QVBoxLayout()
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self.tabs)

        container = QWidget()
        container.setObjectName("app")
        container.setLayout(layout)
        self.setCentralWidget(container)
        self._apply_style()
        self._load_trades()

        self.buy_button.clicked.connect(
            lambda: self._buy(
                "Compra manual de todo el efectivo disponible",
                self.settings.max_position_fraction,
                self.account.all_available_buy_value(self.settings.fee_rate),
            )
        )
        self.buy_half_button.clicked.connect(
            lambda: self._buy("Compra manual del 50 %", 0.50)
        )
        self.sell_button.clicked.connect(lambda: self._sell("Venta manual"))
        self.bot_toggle.toggled.connect(self._on_bot_toggled)
        self.settings_button.clicked.connect(self._open_settings)
        self.reset_button.clicked.connect(self._reset_simulation)
        self.backtest_button.clicked.connect(self._run_backtest)
        self.source_combo.currentIndexChanged.connect(self._change_market_source)
        self.timeframe_combo.currentTextChanged.connect(self._change_timeframe)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1_000)
        self._refresh()

    def _on_bot_toggled(self, enabled: bool) -> None:
        if enabled:
            if self.keep_awake.start():
                self.power_status_label.setText(
                    "Energía: bot activo · la pantalla puede apagarse, "
                    "pero el Mac permanecerá despierto"
                )
            else:
                self.power_status_label.setText(
                    "Energía: no se pudo impedir el reposo del Mac"
                )
        else:
            self.keep_awake.stop()
            self.power_status_label.setText(
                "Energía: comportamiento normal del Mac"
            )

    def _change_market_source(self) -> None:
        source = self.source_combo.currentData()
        self._stop_market_worker()
        self.market_mode = source
        self.live_signal_pending = False
        if source == "simulated":
            self.timeframe_combo.setEnabled(False)
            self.connection_label.setText("● Simulación local")
            self.connection_label.setStyleSheet("color: #94a3b8;")
            self.prices = [self.market.price]
            self._refresh()
            return
        self.timeframe_combo.setEnabled(True)
        self.last_live_update = 0.0
        self.connection_label.setText("● Conectando…")
        self.connection_label.setStyleSheet("color: #fbbf24;")
        self.market_worker = LiveMarketWorker(
            source,
            "BTC/EUR",
            self.data_dir / "market_candles.sqlite",
            self,
        )
        self.market_worker.ticker.connect(self._on_live_ticker)
        self.market_worker.candle_closed.connect(self._on_live_candle)
        self.market_worker.history_ready.connect(self._on_live_history)
        self.market_worker.status.connect(self._on_market_status)
        self.market_worker.start()

    def _stop_market_worker(self) -> None:
        if self.market_worker is not None:
            self.market_worker.stop()
            self.market_worker = None

    def _on_live_ticker(self, ticker: dict) -> None:
        self.market.price = ticker["last"]
        self.live_bid = ticker["bid"]
        self.live_ask = ticker["ask"]
        self.last_live_update = time.time()
        updated = datetime.fromtimestamp(ticker["timestamp"] / 1000).strftime("%H:%M:%S")
        self.connection_label.setText(f"● En vivo · {updated}")
        self.connection_label.setStyleSheet("color: #34d399;")
        self.connection_label.setToolTip(
            f"Bid {self.live_bid:,.2f} € · Ask {self.live_ask:,.2f} €"
        )
        self._refresh()

    def _on_live_history(self, histories: dict) -> None:
        self.live_histories = histories
        self._change_timeframe(self.timeframe_combo.currentText())

    def _on_live_candle(self, timeframe: str, candle: Candle) -> None:
        candles = self.live_histories.setdefault(timeframe, [])
        if not candles or candles[-1].timestamp_ms < candle.timestamp_ms:
            candles.append(candle)
        else:
            candles[-1] = candle
        self.live_histories[timeframe] = candles[-1000:]
        if timeframe == "1h":
            self.live_signal_pending = True
            self.live_volume_1h = candle.volume
        if timeframe == self.timeframe_combo.currentText():
            self.prices = [item.close for item in candles]
            self._refresh()

    def _on_market_status(self, status: str, detail: str) -> None:
        colors = {"LIVE": "#34d399", "CONNECTING": "#fbbf24",
                  "RECONNECTING": "#fbbf24", "ERROR": "#f87171"}
        labels = {"LIVE": "Datos en vivo", "CONNECTING": detail,
                  "RECONNECTING": "Reconectando", "ERROR": "Sin conexión"}
        self.connection_label.setText(f"● {labels.get(status, detail)}")
        self.connection_label.setToolTip(detail)
        self.connection_label.setStyleSheet(
            f"color: {colors.get(status, '#94a3b8')};"
        )

    def _change_timeframe(self, timeframe: str) -> None:
        if self.market_mode == "simulated":
            return
        candles = self.live_histories.get(timeframe, [])
        if candles:
            self.prices = [candle.close for candle in candles]
            self._refresh()

    def _tick(self) -> None:
        live = self.market_mode != "simulated"
        if live:
            hourly_candles = self.live_histories.get("1h", [])
            strategy_prices = [candle.close for candle in hourly_candles]
            five_prices = [
                candle.close for candle in self.live_histories.get("5m", [])
            ]
            daily_prices = [
                candle.close for candle in self.live_histories.get("1d", [])
            ]
            highs = [candle.high for candle in hourly_candles]
            lows = [candle.low for candle in hourly_candles]
            allow_strategy = self.live_signal_pending
            self.live_signal_pending = False
        else:
            self.prices.append(self.market.tick())
            strategy_prices = self.prices
            five_prices = self.prices
            daily_prices = []
            highs = lows = None
            allow_strategy = True
        technical = self.strategy.evaluate(
            strategy_prices, five_prices, daily_prices, highs, lows
        )
        signal = technical.action if allow_strategy else "ESPERAR"
        self.current_size_factor = technical.size_factor
        signal_colors = {
            "COMPRAR": "#34d399",
            "VENDER": "#f87171",
            "ESPERAR": "#94a3b8",
        }
        self.signal_label.setText(f"● {signal}")
        self.signal_label.setStyleSheet(
            f"color: {signal_colors.get(signal, '#94a3b8')};"
        )
        self.account.record_equity(self.market.price)
        if self.bot_toggle.isChecked():
            if self.account.cooldown_remaining > 0:
                self.account.cooldown_remaining -= 1
            if self.account.buy_cooldown_remaining > 0:
                self.account.buy_cooldown_remaining -= 1
            if self.account.post_sale_cooldown_remaining > 0:
                self.account.post_sale_cooldown_remaining -= 1
            self.account.update_reentry_reference(
                self.market.price,
                self.settings.stable_reference_ticks,
                self.settings.stable_reference_range,
            )
            rebound_failed = self.account.update_defensive_exit(
                self.market.price,
                technical.bearish_confirmation,
                self.settings.stable_reference_ticks,
                self.settings.stable_reference_range,
                self.settings.rebound_from_floor,
            )

            stopped, stop_kind = self.account.stopped_lots(
                self.market.price,
                self.settings.stop_loss,
                self.settings.trailing_activation,
                self.settings.trailing_distance,
            )
            if stopped:
                trade = self.account.sell_selected_lots(
                    stopped,
                    self.market.price,
                    f"{stop_kind} ({len(stopped)} lote/s)",
                    self.settings.fee_rate,
                    self.settings.slippage_rate,
                )
                self.account.record_sale_result(trade.pnl_eur)
                self.account.cooldown_remaining = self.settings.cooldown_ticks
                self.account.register_sale(
                    self.market.price,
                    self.settings.post_sale_cooldown_ticks,
                )
                self._append_trade()
                self.bot_status_label.setText(f"Bot: {stop_kind} ejecutado")
                self.decision_label.setText(
                    f"Decisión actual: venta de protección; cooldown de "
                    f"{self.settings.cooldown_ticks} ciclos."
                )
                self._save()
                self._refresh()
                return

            defensive = []
            if (
                self.account.bearish_confirmation_count
                >= self.settings.bearish_confirmation_ticks
            ):
                defensive = self.account.losing_lots(
                    self.market.price, self.settings.defensive_loss
                )
            if rebound_failed:
                defensive_ids = {id(lot) for lot in defensive}
                defensive.extend(
                    lot for lot in self.account.lots
                    if id(lot) not in defensive_ids
                    and self.market.price
                    < (lot.entry_price_eur or lot.cost_basis_eur / lot.bitcoin)
                )
            if defensive:
                reason = (
                    "Rebote fallido con EMA/MACD bajistas"
                    if rebound_failed else
                    "Venta defensiva: -3 % y tendencia bajista"
                )
                trade = self.account.sell_selected_lots(
                    defensive,
                    self.market.price,
                    reason,
                    self.settings.fee_rate,
                    self.settings.slippage_rate,
                )
                self.account.record_sale_result(trade.pnl_eur)
                self.account.register_sale(
                    self.market.price,
                    self.settings.post_sale_cooldown_ticks,
                )
                self._append_trade()
                self._save()
                self.bot_status_label.setText(f"Bot: {reason}")
                self._refresh()
                return

            profitable = self.account.profitable_lots(
                self.market.price,
                self.settings.sell_gain,
                self.settings.fee_rate,
                self.settings.slippage_rate,
            )
            if profitable:
                trade = self.account.sell_profitable_lots(
                    self.market.price,
                    self.settings.sell_gain,
                    f"Objetivo individual alcanzado ({len(profitable)} lote/s)",
                    fee_rate=self.settings.fee_rate,
                    slippage_rate=self.settings.slippage_rate,
                )
                self.account.record_sale_result(trade.pnl_eur)
                self.account.register_sale(
                    self.market.price,
                    self.settings.post_sale_cooldown_ticks,
                )
                self._append_trade()
                self._save()
                self.bot_status_label.setText(
                    f"Bot: venta de {len(profitable)} lote/s rentable/s"
                )
                self._refresh()
                return
            if allow_strategy:
                action, status = technical.action, technical.status
            else:
                action, status = "ESPERAR", "Esperando cierre de vela 1h"
            pause_reason = self._risk_pause_reason() or self._market_pause_reason()
            self.bot_status_label.setText(f"Bot: {status}")
            self.decision_label.setText(
                f"Decisión actual: {self._decision_explanation(action, status)} "
                f"RSI {technical.rsi:.1f} · ATR {technical.volatility:.2%}."
            )
            lower_entry = self.account.price_allows_next_buy(
                self.market.price,
                self.settings.minimum_buy_price_drop,
            )
            entry_confirmed = lower_entry or technical.ema_confirmation
            reentry_allowed = self.account.post_sale_buy_allowed(
                self.market.price,
                self.settings.reentry_pullback,
                technical.ema_confirmation,
            )
            if (
                action == "COMPRAR"
                and not pause_reason
                and self.account.cooldown_remaining == 0
                and self.account.buy_cooldown_remaining == 0
                and entry_confirmed
                and reentry_allowed
                and self.account.can_buy(
                    self.market.price,
                    fee_rate=self.settings.fee_rate,
                )
            ):
                reason = (
                    f"Precio {self.settings.minimum_buy_price_drop:.1%} "
                    "bajo la última compra"
                    if lower_entry else
                    "Confirmación técnica EMA y multi-indicador"
                )
                self._buy_risk_sized(reason)
            elif action == "COMPRAR":
                reason = pause_reason or (
                    f"cooldown: quedan {self.account.cooldown_remaining} ciclos"
                    if self.account.cooldown_remaining else
                    (
                        "separación entre compras: quedan "
                        f"{self.account.buy_cooldown_remaining} ciclos"
                        if self.account.buy_cooldown_remaining else
                        (
                            "reentrada tras venta aún no confirmada"
                            if not reentry_allowed else
                            (
                            "el precio aún no ha bajado "
                            f"{self.settings.minimum_buy_price_drop:.1%} "
                            "desde la última compra"
                            if not entry_confirmed else
                            "no alcanza la compra mínima manteniendo la reserva"
                            )
                        )
                    )
                )
                self.bot_status_label.setText(f"Bot: compra pausada · {reason}")
                self.decision_label.setText(
                    f"Decisión actual: no compra por {reason}."
                )
        else:
            self.bot_status_label.setText("Bot: desactivado")
            self.decision_label.setText(
                "Decisión actual: bot desactivado; solo se permiten operaciones manuales."
            )
        self._refresh()

    def _decision_explanation(self, action: str, status: str) -> str:
        if action == "COMPRAR":
            return "se confirmó una bajada suficiente y está comprobando los límites de compra."
        if "baj" in status.lower() or "compra" in status.lower():
            return "ha detectado una bajada, pero todavía espera la confirmación configurada."
        if "sub" in status.lower() or "venta" in status.lower():
            return "vigila la subida; cada lote se venderá al alcanzar su objetivo neto."
        return "no existe todavía una señal válida; continúa observando nuevos precios."

    def _risk_pause_reason(self) -> str:
        now = datetime.now()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = day_start - timedelta(days=day_start.weekday())
        daily = self.account.realized_loss_since(day_start)
        weekly = self.account.realized_loss_since(week_start)
        if daily >= self.account.initial_cash_eur * self.settings.daily_loss_limit:
            return "límite de pérdida diaria alcanzado"
        if weekly >= self.account.initial_cash_eur * self.settings.weekly_loss_limit:
            return "límite de pérdida semanal alcanzado"
        if self.account.consecutive_losses >= self.settings.max_consecutive_losses:
            return "dos pérdidas consecutivas; requiere reinicio manual"
        if self.account.max_drawdown >= self.settings.max_drawdown_limit:
            return "caída máxima del 10 %; requiere revisión"
        return ""

    def _market_pause_reason(self) -> str:
        if self.market_mode == "simulated":
            return ""
        if not self.last_live_update or time.time() - self.last_live_update > 30:
            return "datos de mercado desactualizados"
        if self.live_bid > 0 and self.live_ask > 0:
            midpoint = (self.live_bid + self.live_ask) / 2
            spread = (self.live_ask - self.live_bid) / midpoint
            if spread > self.settings.max_spread:
                return f"spread demasiado alto ({spread:.2%})"
        return ""

    def _buy_risk_sized(self, reason: str) -> None:
        value = self.account.all_available_buy_value(self.settings.fee_rate)
        self._buy(
            reason,
            self.settings.max_position_fraction,
            value,
            show_dialog=False,
        )

    def _buy(
        self,
        reason: str,
        fraction: float,
        requested_value: float | None = None,
        show_dialog: bool = True,
    ) -> None:
        try:
            self.account.minimum_cash_eur = self.settings.minimum_cash_eur
            self.account.minimum_trade_eur = self.settings.minimum_trade_eur
            requested = (
                self.account.equity(self.market.price) * fraction
                if requested_value is None else requested_value
            )
            self.account.buy(
                self.market.price,
                requested,
                reason,
                max_fraction=fraction,
                fee_rate=self.settings.fee_rate,
                slippage_rate=self.settings.slippage_rate,
            )
            if not show_dialog:
                self.account.buy_cooldown_remaining = (
                    self.settings.buy_spacing_ticks
                )
            self._append_trade()
            self._save()
        except ValueError as error:
            if show_dialog:
                QMessageBox.information(self, "No se puede comprar", str(error))
            else:
                self.bot_status_label.setText("Bot: compra omitida · continúa activo")
                self.decision_label.setText(
                    f"Decisión actual: {error} El bot seguirá vigilando el mercado."
                )
        self._refresh()

    def _sell(self, reason: str) -> None:
        try:
            trade = self.account.sell_all(
                self.market.price,
                reason,
                fee_rate=self.settings.fee_rate,
                slippage_rate=self.settings.slippage_rate,
            )
            self.account.record_sale_result(trade.pnl_eur)
            self.account.register_sale(
                self.market.price,
                self.settings.post_sale_cooldown_ticks,
            )
            self._append_trade()
            self._save()
        except ValueError as error:
            QMessageBox.information(self, "No se puede vender", str(error))
        self._refresh()

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.Accepted:
            dialog.apply_to(self.settings)
            self.account.minimum_cash_eur = self.settings.minimum_cash_eur
            self.account.minimum_trade_eur = self.settings.minimum_trade_eur
            self.account.max_position_fraction = self.settings.max_position_fraction
            self.account.max_open_lots = self.settings.max_open_lots
            self._save()
            self._refresh()

    def _reset_simulation(self) -> None:
        answer = QMessageBox.question(
            self,
            "Reiniciar simulación",
            (
                "¿Quieres borrar todas las operaciones y empezar de nuevo?\n\n"
                "El saldo volverá a 10.000 €, la posición BTC quedará a cero "
                "y el precio simulado volverá a 90.000 €. Tus ajustes se conservarán."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.bot_toggle.setChecked(False)
        self.account = PaperAccount(
            minimum_cash_eur=self.settings.minimum_cash_eur,
            minimum_trade_eur=self.settings.minimum_trade_eur,
            max_open_lots=self.settings.max_open_lots,
        )
        self.market = PriceSimulator(initial_price=90_000.0)
        self.strategy = MultiIndicatorStrategy()
        self.prices = [self.market.price]
        self.table.setRowCount(0)
        self.signal_label.setText("● ESPERAR")
        self.signal_label.setStyleSheet("color: #94a3b8;")
        self.bot_status_label.setText("Bot: esperando tendencia")
        self.risk_status_label.setText("Riesgo: sin posiciones abiertas")
        self.decision_label.setText(
            "Decisión actual: simulación reiniciada; esperando nuevos precios."
        )
        self._save()
        self._refresh()

    def _run_backtest(self) -> None:
        self.backtest_button.setEnabled(False)
        self.backtest_button.setText("Descargando histórico…")
        QApplication.processEvents()
        try:
            prices = download_coinbase_daily_prices()
            result = run_backtest(prices, self.settings)
            QMessageBox.information(
                self,
                "Backtest BTC-EUR · Coinbase",
                (
                    f"Velas diarias: {len(prices)}\n"
                    f"Capital final: {result.ending_equity:,.2f} €\n"
                    f"Rentabilidad: {result.return_percent:+.2f} %\n"
                    f"Beneficio realizado: {result.realized_profit:+,.2f} €\n"
                    f"Comisiones: {result.total_fees:,.2f} €\n"
                    f"Caída máxima: {result.max_drawdown_percent:.2f} %\n"
                    f"Operaciones: {result.trades}\n\n"
                    f"Salidas por stop: {result.stop_exits}\n"
                    f"Ventas ganadoras: {result.winning_sales}\n"
                    f"Ventas no ganadoras: {result.losing_sales}\n"
                    f"Porcentaje de aciertos: {result.win_rate_percent:.1f} %\n"
                    f"Rentabilidad anualizada: {result.annualized_return_percent:+.2f} %\n"
                    f"Comprar y mantener: {result.buy_hold_return_percent:+.2f} %\n"
                    f"Diferencia frente a mantener: {result.excess_return_percent:+.2f} %\n\n"
                    "Resultado histórico orientativo; no predice resultados futuros."
                ),
            )
        except Exception as error:
            QMessageBox.warning(
                self,
                "No se pudo ejecutar el backtest",
                f"No se pudo descargar o procesar el histórico:\n{error}",
            )
        finally:
            self.backtest_button.setEnabled(True)
            self.backtest_button.setText("↗ Backtest histórico")

    def _load_trades(self) -> None:
        for _ in self.account.trades:
            self._append_trade()

    def _append_trade(self) -> None:
        trade_index = self.table.rowCount()
        if trade_index >= len(self.account.trades):
            return
        trade = self.account.trades[trade_index]
        self.table.insertRow(trade_index)
        values = [
            trade.timestamp.strftime("%d/%m %H:%M"),
            trade.side,
            f"{trade.bitcoin:.6f}",
            f"{trade.price_eur:,.2f} €",
            f"{trade.fee_eur:,.2f} €",
            f"{trade.pnl_eur:+,.2f} €" if trade.side == "VENTA" else "—",
            trade.reason,
        ]
        for column, value in enumerate(values):
            self.table.setItem(trade_index, column, QTableWidgetItem(value))

    def _refresh(self) -> None:
        price = self.market.price
        equity = self.account.equity(price)
        total_profit = equity - self.account.initial_cash_eur
        self.account.record_equity(price)
        target = self.account.next_lot_target_price(
            self.settings.sell_gain,
            self.settings.fee_rate,
            self.settings.slippage_rate,
        )
        stop = self.account.next_stop_price(
            self.settings.stop_loss,
            self.settings.trailing_activation,
            self.settings.trailing_distance,
        )
        self.price_label.setText(f"BTC  {price:,.2f} €")
        target_text = f"{target:,.2f} €" if target else "—"
        self.cards["cash"].set_value(
            f"{self.account.cash_eur:,.2f} €",
            (
                f"Reserva: {self.account.minimum_cash_eur:,.0f} € · "
                f"compra mín.: {self.account.minimum_trade_eur:,.0f} €"
            ),
        )
        self.cards["bitcoin"].set_value(
            f"{self.account.bitcoin:.6f} BTC",
            f"Coste medio: {self.account.average_cost_eur:,.0f} €",
        )
        self.cards["equity"].set_value(
            f"{equity:,.2f} €",
            f"Inicial: {self.account.initial_cash_eur:,.0f} €",
        )
        self.cards["profit"].set_value(
            f"{total_profit:+,.2f} €",
            f"{total_profit / self.account.initial_cash_eur:+.2%}",
        )
        pause = self._risk_pause_reason()
        cooldown = self.account.cooldown_remaining
        buy_spacing = self.account.buy_cooldown_remaining
        stop_text = f"{stop:,.0f} €" if stop else "—"
        self.risk_status_label.setText(
            f"Riesgo: stop {stop_text} · objetivo {target_text} · "
            f"riesgo/operación {self.settings.risk_per_trade:.1%} · "
            f"cooldown {cooldown} · próxima compra {buy_spacing} · "
            f"lotes {len(self.account.lots)}/{self.account.max_open_lots}"
            + (
                f" · spread {(self.live_ask - self.live_bid) / ((self.live_ask + self.live_bid) / 2):.2%}"
                if self.market_mode != "simulated" and self.live_bid and self.live_ask
                else ""
            )
            + (
                f" · vol1h {self.live_volume_1h:,.1f} BTC"
                if self.market_mode != "simulated" and self.live_volume_1h
                else ""
            )
            + (f" · PAUSADO: {pause}" if pause else "")
        )
        now = datetime.now()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        daily_loss = self.account.realized_loss_since(day_start)
        daily_limit = self.account.initial_cash_eur * self.settings.daily_loss_limit
        risk_ratio = min(daily_loss / max(daily_limit, 0.01), 1.0)
        self.drawdown_bar.setValue(round(risk_ratio * 1000))
        self.drawdown_bar.setFormat(
            f"Pérdida diaria {daily_loss:,.0f} € / límite {daily_limit:,.0f} € · "
            f"caída máxima histórica {self.account.max_drawdown:.1%}"
        )
        self.chart.set_data(
            self.prices,
            self.account.trades,
            self.account.lots,
            (stop, target),
        )

    def _save(self) -> None:
        try:
            save_state(self.state_path, self.account, self.settings)
        except OSError:
            pass

    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop_market_worker()
        self.keep_awake.stop()
        self._save()
        event.accept()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget#app { background: #0b1220; color: #e5e7eb; }
            QLabel#brandIcon {
                background: #f59e0b; color: #0b1220; border-radius: 21px;
                font-size: 28px; font-weight: 900; min-width: 42px;
                min-height: 42px; max-width: 42px; max-height: 42px;
                qproperty-alignment: AlignCenter;
            }
            QLabel#brandTitle { color: white; font-size: 17px; font-weight: 900; }
            QLabel#brandSubtitle { color: #64748b; font-size: 11px; }
            QLabel#price { color: #fbbf24; font-size: 30px; font-weight: 800; }
            QLabel#signalBadge {
                background: #172033; border: 1px solid #334155;
                border-radius: 13px; padding: 6px 12px; font-weight: 800;
                color: #94a3b8;
            }
            QLabel#sectionTitle {
                color: #94a3b8; font-size: 11px; font-weight: 900;
                letter-spacing: 1px;
            }
            QFrame#metricCard, QFrame#panel {
                background: #111827; border: 1px solid #1f2a3d;
                border-radius: 12px;
            }
            QLabel#cardTitle { color: #64748b; font-size: 10px; font-weight: 800; }
            QLabel#cardValue { font-size: 19px; font-weight: 900; }
            QLabel#cardDetail { color: #94a3b8; font-size: 11px; }
            QLabel#botStatus, QLabel#riskStatus, QLabel#powerStatus,
            QLabel#decisionStatus {
                background: #172033; border: 1px solid #26344d;
                border-radius: 8px; padding: 9px; font-size: 12px;
            }
            QLabel#botStatus { color: #93c5fd; }
            QLabel#riskStatus { color: #fbbf24; }
            QLabel#powerStatus { color: #86efac; }
            QLabel#decisionStatus { color: #cbd5e1; }
            QLabel#connectionStatus { color: #94a3b8; font-weight: 700; }
            QComboBox {
                background: #172033; border: 1px solid #334155;
                border-radius: 8px; color: #e5e7eb; padding: 7px 10px;
            }
            QPushButton {
                background: #334155; border: none; border-radius: 9px;
                color: white; font-weight: 700; padding: 10px 15px;
            }
            QPushButton:hover { background: #475569; }
            QPushButton#buyButton { background: #059669; }
            QPushButton#buyButton:hover { background: #10b981; }
            QPushButton#sellButton { background: #dc2626; }
            QPushButton#sellButton:hover { background: #ef4444; }
            QPushButton#resetButton { background: #92400e; }
            QPushButton#resetButton:hover { background: #b45309; }
            QCheckBox { color: #e5e7eb; font-weight: 700; spacing: 8px; }
            QTabWidget::pane { border: none; }
            QTabBar::tab {
                background: transparent; color: #64748b; padding: 9px 16px;
                border-bottom: 2px solid transparent; font-weight: 700;
            }
            QTabBar::tab:selected {
                color: #fbbf24; border-bottom: 2px solid #f59e0b;
            }
            QProgressBar#riskBar {
                background: #0f172a; border: 1px solid #26344d;
                border-radius: 7px; color: white; height: 19px;
                text-align: center; font-size: 10px; font-weight: 700;
            }
            QProgressBar#riskBar::chunk {
                background: #f59e0b; border-radius: 6px;
            }
            QTableWidget {
                background: #111827; alternate-background-color: #172033;
                border: 1px solid #26344d; border-radius: 8px;
                color: #e5e7eb; gridline-color: #26344d;
            }
            QHeaderView::section {
                background: #1f2937; color: #cbd5e1; border: none;
                padding: 8px; font-weight: 700;
            }
            QDialog { background: #111827; color: #e5e7eb; }
            QDoubleSpinBox, QSpinBox {
                background: #1f2937; color: white; padding: 5px;
                border: 1px solid #334155; border-radius: 5px;
            }
            """
        )


def run() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Bitcoin Paper Bot 1 Lote")
    app.setOrganizationName("Santiago")
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
