from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import time

from PySide6.QtCore import QThread, Signal


@dataclass(frozen=True)
class Candle:
    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @classmethod
    def from_ccxt(cls, values: list) -> "Candle":
        return cls(int(values[0]), *(float(value) for value in values[1:6]))


class CandleStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def save(self, exchange: str, symbol: str, timeframe: str, candles: list[Candle]) -> None:
        if not candles:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS candles (
                    exchange TEXT NOT NULL, symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL, timestamp_ms INTEGER NOT NULL,
                    open REAL, high REAL, low REAL, close REAL, volume REAL,
                    PRIMARY KEY (exchange, symbol, timeframe, timestamp_ms)
                )"""
            )
            connection.executemany(
                """INSERT OR REPLACE INTO candles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [(exchange, symbol, timeframe, c.timestamp_ms, c.open, c.high,
                  c.low, c.close, c.volume) for c in candles],
            )

    def load(self, exchange: str, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        if not self.path.exists():
            return []
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                """SELECT timestamp_ms, open, high, low, close, volume
                FROM candles WHERE exchange=? AND symbol=? AND timeframe=?
                ORDER BY timestamp_ms DESC LIMIT ?""",
                (exchange, symbol, timeframe, limit),
            ).fetchall()
        return [Candle(*row) for row in reversed(rows)]


class LiveMarketWorker(QThread):
    ticker = Signal(dict)
    candle_closed = Signal(str, object)
    history_ready = Signal(dict)
    status = Signal(str, str)

    def __init__(self, exchange_id: str, symbol: str, database_path: Path, parent=None) -> None:
        super().__init__(parent)
        self.exchange_id = exchange_id
        self.symbol = symbol
        self.store = CandleStore(database_path)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.tasks: list[asyncio.Task] = []
        self.main_task: asyncio.Task | None = None

    def run(self) -> None:
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.main_task = self.loop.create_task(self._run_streams())
            self.loop.run_until_complete(self.main_task)
        except asyncio.CancelledError:
            pass
        except Exception as error:
            self.status.emit("ERROR", str(error))
        finally:
            if self.loop is not None:
                self.loop.close()
            self.loop = None
            self.main_task = None

    async def _run_streams(self) -> None:
        try:
            import ccxt.pro as ccxtpro
        except ImportError:
            self.status.emit("ERROR", "Falta instalar la dependencia ccxt.")
            return
        exchange_class = getattr(ccxtpro, self.exchange_id, None)
        if exchange_class is None:
            self.status.emit("ERROR", f"Exchange no compatible: {self.exchange_id}")
            return
        exchange = exchange_class({"enableRateLimit": True})
        try:
            self.status.emit("CONNECTING", "Descargando histórico…")
            await exchange.load_markets()
            if self.symbol not in exchange.markets:
                raise ValueError(f"{self.symbol} no está disponible en {exchange.name}.")
            history: dict[str, list[Candle]] = {}
            for timeframe, limit in (("5m", 500), ("1h", 1000), ("1d", 1000)):
                cached = self.store.load(self.exchange_id, self.symbol, timeframe, limit)
                fetched = [Candle.from_ccxt(row) for row in await exchange.fetch_ohlcv(
                    self.symbol, timeframe=timeframe, limit=limit
                )]
                self.store.save(self.exchange_id, self.symbol, timeframe, fetched)
                merged = {c.timestamp_ms: c for c in cached + fetched}
                history[timeframe] = sorted(
                    merged.values(), key=lambda candle: candle.timestamp_ms
                )[-limit:]
            self.history_ready.emit(history)
            self.status.emit("LIVE", "Datos en vivo")
            self.tasks = [asyncio.create_task(self._watch_ticker(exchange))]
            self.tasks.extend(asyncio.create_task(self._watch_candles(exchange, timeframe))
                              for timeframe in ("5m", "1h", "1d"))
            await asyncio.gather(*self.tasks)
        finally:
            self.tasks = []
            await exchange.close()

    async def _watch_ticker(self, exchange) -> None:
        failures = 0
        while not self.isInterruptionRequested():
            try:
                value = await exchange.watch_ticker(self.symbol)
                last = value.get("last") or value.get("close")
                if last:
                    self.ticker.emit({
                        "last": float(last), "bid": float(value.get("bid") or 0),
                        "ask": float(value.get("ask") or 0),
                        "timestamp": int(value.get("timestamp") or time.time() * 1000),
                    })
                failures = 0
            except Exception as error:
                failures += 1
                self.status.emit("RECONNECTING", f"Reconectando: {error}")
                await asyncio.sleep(min(2 ** failures, 30))

    async def _watch_candles(self, exchange, timeframe: str) -> None:
        last_closed = 0
        failures = 0
        while not self.isInterruptionRequested():
            try:
                values = await exchange.watch_ohlcv(self.symbol, timeframe=timeframe)
                if len(values) < 2:
                    continue
                candle = Candle.from_ccxt(values[-2])
                if candle.timestamp_ms > last_closed:
                    last_closed = candle.timestamp_ms
                    self.store.save(self.exchange_id, self.symbol, timeframe, [candle])
                    self.candle_closed.emit(timeframe, candle)
                failures = 0
            except Exception as error:
                failures += 1
                self.status.emit("RECONNECTING", f"Reconectando velas: {error}")
                await asyncio.sleep(min(2 ** failures, 30))

    def stop(self) -> None:
        self.requestInterruption()
        if self.loop is not None:
            self.loop.call_soon_threadsafe(
                lambda: (
                    [task.cancel() for task in self.tasks],
                    self.main_task.cancel() if self.main_task else None,
                )
            )
        self.wait(5_000)
