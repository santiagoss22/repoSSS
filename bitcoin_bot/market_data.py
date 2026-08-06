from __future__ import annotations

import asyncio
import csv
from dataclasses import dataclass
import io
from pathlib import Path
import re
import sqlite3
import struct
import time
from urllib.request import Request, urlopen
import zlib

from PySide6.QtCore import QThread, Signal


PUBLIC_MARKET_SOURCES = {
    "binance": "Binance · BTC/EUR (solo datos)",
    "coinbase": "Coinbase · BTC/EUR (solo datos)",
    "kraken": "Kraken · BTC/EUR (solo datos)",
}

# La simulación trata sus órdenes como taker (ejecución inmediata). Kraken
# aplica tarifas por nivel; usamos el nivel inicial para no sobreestimar el
# resultado del paper trading.
SIMULATED_TAKER_FEES = {"kraken": 0.008, "kraken_replay": 0.008}

KRAKEN_ARCHIVE_ID = "1ptNqWYidLkhb2VAKuLCxmp2OXEfGO-AP"
KRAKEN_HOURLY_FILENAME = "master_q4/XBTEUR_60.csv"
KRAKEN_REPLAY_START_MS = 1_420_070_400_000
KRAKEN_REPLAY_END_MS = 1_767_225_600_000


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


def parse_kraken_hourly_csv(data: bytes) -> list[Candle]:
    candles: list[Candle] = []
    for row in csv.reader(io.StringIO(data.decode("utf-8-sig"))):
        if len(row) < 6 or not row[0].strip().isdigit():
            continue
        timestamp = int(row[0])
        if timestamp < 10_000_000_000:
            timestamp *= 1000
        candles.append(
            Candle(timestamp, *(float(value) for value in row[1:6]))
        )
    return sorted(candles, key=lambda candle: candle.timestamp_ms)


def kraken_replay_period(candles: list[Candle]) -> list[Candle]:
    """Limita el paper trading al histórico completo 2015–2025."""
    return [
        candle for candle in candles
        if KRAKEN_REPLAY_START_MS <= candle.timestamp_ms < KRAKEN_REPLAY_END_MS
    ]


def _kraken_archive_download_url() -> str:
    page = urlopen(
        f"https://drive.google.com/uc?export=download&id={KRAKEN_ARCHIVE_ID}",
        timeout=30,
    ).read().decode("utf-8", errors="replace")
    match = re.search(r'name="uuid" value="([^"]+)"', page)
    if not match:
        raise RuntimeError("Kraken no devolvió el permiso temporal de descarga.")
    return (
        "https://drive.usercontent.google.com/download"
        f"?id={KRAKEN_ARCHIVE_ID}&export=download&confirm=t"
        f"&uuid={match.group(1)}"
    )


def _download_range(url: str, byte_range: str) -> bytes:
    request = Request(
        url,
        headers={"Range": f"bytes={byte_range}", "User-Agent": "BitcoinPaperBot/1.0"},
    )
    with urlopen(request, timeout=60) as response:
        return response.read()


def _zip64_local_offset(extra: bytes, fields: tuple) -> int:
    cursor = 0
    while cursor + 4 <= len(extra):
        tag, length = struct.unpack_from("<HH", extra, cursor)
        value = extra[cursor + 4 : cursor + 4 + length]
        cursor += 4 + length
        if tag != 0x0001:
            continue
        position = 0
        for original in (fields[9], fields[8], fields[-1]):
            if original == 0xFFFFFFFF:
                replacement = struct.unpack_from("<Q", value, position)[0]
                position += 8
                if original == fields[-1]:
                    return replacement
    return fields[-1]


def download_kraken_hourly_history(cache_path: Path) -> list[Candle]:
    """Extrae solo BTC/EUR 1h del ZIP oficial de 7,3 GB mediante rangos HTTP."""
    if cache_path.exists() and cache_path.stat().st_size > 100_000:
        return kraken_replay_period(parse_kraken_hourly_csv(cache_path.read_bytes()))

    url = _kraken_archive_download_url()
    tail = _download_range(url, "-65536")
    zip64_index = tail.rfind(b"PK\x06\x06")
    if zip64_index < 0:
        raise RuntimeError("No se encontró el índice ZIP64 de Kraken.")
    zip64 = struct.unpack_from("<4sQ2H2L4Q", tail, zip64_index)
    central_size, central_offset = zip64[-2], zip64[-1]
    central = _download_range(
        url, f"{central_offset}-{central_offset + central_size - 1}"
    )

    position = 0
    selected: tuple[int, int, int] | None = None
    while position + 46 <= len(central):
        if central[position : position + 4] != b"PK\x01\x02":
            break
        fields = struct.unpack_from("<4s6H3L5H2L", central, position)
        name_length, extra_length, comment_length = fields[10:13]
        name_start = position + 46
        name = central[name_start : name_start + name_length].decode("utf-8")
        extra = central[
            name_start + name_length : name_start + name_length + extra_length
        ]
        if name == KRAKEN_HOURLY_FILENAME:
            selected = (
                _zip64_local_offset(extra, fields), fields[8], fields[4]
            )
            break
        position += 46 + name_length + extra_length + comment_length
    if selected is None:
        raise RuntimeError("No se encontró XBTEUR_60.csv en el histórico de Kraken.")

    local_offset, compressed_size, method = selected
    header = _download_range(url, f"{local_offset}-{local_offset + 29}")
    if header[:4] != b"PK\x03\x04":
        raise RuntimeError("Cabecera de histórico Kraken no válida.")
    name_length, extra_length = struct.unpack_from("<HH", header, 26)
    data_offset = local_offset + 30 + name_length + extra_length
    compressed = _download_range(
        url, f"{data_offset}-{data_offset + compressed_size - 1}"
    )
    if method == 8:
        raw = zlib.decompress(compressed, -zlib.MAX_WBITS)
    elif method == 0:
        raw = compressed
    else:
        raise RuntimeError(f"Compresión ZIP no compatible: {method}")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(raw)
    return kraken_replay_period(parse_kraken_hourly_csv(raw))


class KrakenHistoryLoader(QThread):
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, cache_path: Path, parent=None) -> None:
        super().__init__(parent)
        self.cache_path = cache_path

    def run(self) -> None:
        try:
            self.ready.emit(download_kraken_hourly_history(self.cache_path))
        except Exception as error:
            self.failed.emit(str(error))


class LiveMarketWorker(QThread):
    ticker = Signal(dict)
    candle_closed = Signal(str, object)
    history_ready = Signal(dict)
    status = Signal(str, str)

    def __init__(self, exchange_id: str, symbol: str, database_path: Path, parent=None) -> None:
        super().__init__(parent)
        if exchange_id not in PUBLIC_MARKET_SOURCES:
            raise ValueError(f"Fuente pública no permitida: {exchange_id}")
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
