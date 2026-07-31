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
    return PaperAccount(**account_data), BotSettings.from_dict(data.get("settings", {}))
