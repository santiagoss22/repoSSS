from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path

from bitcoin_bot.config import BotSettings
from bitcoin_bot.simulator import PaperAccount, PositionLot, Trade


def save_state(path: Path, account: PaperAccount, settings: BotSettings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    account_data = asdict(account)
    account_data["trades"] = [
        {**asdict(trade), "timestamp": trade.timestamp.isoformat()}
        for trade in account.trades
    ]
    account_data["lots"] = [
        {**asdict(lot), "timestamp": lot.timestamp.isoformat()}
        for lot in account.lots
    ]
    payload = {"account": account_data, "settings": settings.to_dict()}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_state(path: Path) -> tuple[PaperAccount, BotSettings]:
    if not path.exists():
        return PaperAccount(), BotSettings()
    data = json.loads(path.read_text(encoding="utf-8"))
    account_data = data.get("account", {})
    account_data["trades"] = [
        Trade(
            **{
                **trade,
                "timestamp": datetime.fromisoformat(trade["timestamp"]),
            }
        )
        for trade in account_data.get("trades", [])
    ]
    if "last_market_price_eur" not in account_data and account_data["trades"]:
        account_data["last_market_price_eur"] = account_data["trades"][-1].price_eur
    account_data["lots"] = [
        PositionLot(
            **{
                **lot,
                "timestamp": datetime.fromisoformat(lot["timestamp"]),
            }
        )
        for lot in account_data.get("lots", [])
    ]
    if (
        account_data.get("bitcoin", 0) > 0
        and not account_data["lots"]
    ):
        account_data["lots"] = [
            PositionLot(
                account_data["bitcoin"],
                account_data.get("cost_basis_eur", 0.0),
            )
        ]
    account = PaperAccount(**account_data)
    _remove_accidental_visual_test_lots(account)
    return account, BotSettings.from_dict(data.get("settings", {}))


def _remove_accidental_visual_test_lots(account: PaperAccount) -> None:
    """Retira ocho lotes creados accidentalmente durante una prueba visual local."""
    accidental_trades = [
        trade for trade in account.trades
        if trade.reason == "prueba"
        and trade.timestamp.isoformat().startswith("2026-08-01T18:01:29")
    ]
    if not accidental_trades:
        return
    accidental_lots = [
        lot for lot in account.lots
        if lot.timestamp.isoformat().startswith("2026-08-01T18:01:29")
        and 90_000 <= lot.entry_price_eur <= 90_070
    ]
    restored_cost = sum(lot.cost_basis_eur for lot in accidental_lots)
    restored_bitcoin = sum(lot.bitcoin for lot in accidental_lots)
    restored_fees = sum(trade.fee_eur for trade in accidental_trades)
    account.cash_eur += restored_cost
    account.bitcoin = max(0.0, account.bitcoin - restored_bitcoin)
    account.cost_basis_eur = max(0.0, account.cost_basis_eur - restored_cost)
    account.total_fees_eur = max(0.0, account.total_fees_eur - restored_fees)
    accidental_lot_ids = {id(lot) for lot in accidental_lots}
    account.lots = [
        lot for lot in account.lots if id(lot) not in accidental_lot_ids
    ]
    account.trades = [trade for trade in account.trades if trade not in accidental_trades]
