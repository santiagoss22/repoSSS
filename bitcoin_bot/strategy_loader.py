from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


AVAILABLE_STRATEGIES = {
    "bot-RSIs": "RSI(6/12/24), EMA y MACD",
    "bot-Envolvente-BOS": "Ruptura de 20h con volumen 1,3× sobre media de 12h",
}


def selected_strategy(settings=None) -> str:
    requested = os.environ.get(
        "BOT_STRATEGY", getattr(settings, "strategy_id", "bot-RSIs")
    )
    return requested if requested in AVAILABLE_STRATEGIES else "bot-RSIs"


def create_strategy(settings=None):
    strategy_id = selected_strategy(settings)
    path = Path(__file__).resolve().parent.parent / "bots" / strategy_id / "strategy.py"
    spec = importlib.util.spec_from_file_location(
        f"bitcoin_bot_strategy_{strategy_id.replace('-', '_')}", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar la estrategia {strategy_id}.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.MultiIndicatorStrategy(settings)
