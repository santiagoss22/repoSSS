import os
import unittest
from unittest.mock import patch

from bitcoin_bot.config import BotSettings
from bitcoin_bot.strategy_loader import AVAILABLE_STRATEGIES, create_strategy


class MultiStrategyTests(unittest.TestCase):
    def test_catalog_contains_both_approved_bots(self):
        self.assertEqual(
            set(AVAILABLE_STRATEGIES), {"bot-RSIs", "bot-Envolvente-BOS"}
        )

    def test_rsi_strategy_is_selected_by_environment(self):
        with patch.dict(os.environ, {"BOT_STRATEGY": "bot-RSIs"}):
            strategy = create_strategy(BotSettings())
        self.assertEqual(strategy.__class__.__module__, "bitcoin_bot_strategy_bot_RSIs")

    def test_bullish_breakout_with_volume_buys_immediately(self):
        with patch.dict(os.environ, {"BOT_STRATEGY": "bot-Envolvente-BOS"}):
            strategy = create_strategy(BotSettings())
        prices = [100.0] * 20 + [102.0]
        signal = strategy.evaluate(
            prices,
            hourly_highs=[101.0] * 20 + [102.3],
            hourly_lows=[99.0] * 20 + [100.2],
            hourly_opens=[100.0] * 20 + [100.5],
            hourly_volumes=[10.0] * 20 + [13.0],
        )
        self.assertEqual(signal.action, "COMPRAR")

    def test_bearish_breakout_with_volume_sells_immediately(self):
        with patch.dict(os.environ, {"BOT_STRATEGY": "bot-Envolvente-BOS"}):
            strategy = create_strategy(BotSettings())
        prices = [100.0] * 20 + [98.0]
        signal = strategy.evaluate(
            prices,
            hourly_highs=[101.0] * 20 + [99.8],
            hourly_lows=[99.0] * 20 + [97.7],
            hourly_opens=[100.0] * 20 + [99.5],
            hourly_volumes=[10.0] * 20 + [13.0],
        )
        self.assertEqual(signal.action, "VENDER")

    def test_breakout_without_required_volume_waits(self):
        with patch.dict(os.environ, {"BOT_STRATEGY": "bot-Envolvente-BOS"}):
            strategy = create_strategy(BotSettings())
        signal = strategy.evaluate(
            [100.0] * 20 + [102.0],
            hourly_highs=[101.0] * 20 + [102.3],
            hourly_lows=[99.0] * 20 + [100.2],
            hourly_opens=[100.0] * 20 + [100.5],
            hourly_volumes=[10.0] * 20 + [12.9],
        )
        self.assertEqual(signal.action, "ESPERAR")

    def test_volume_confirmation_uses_previous_twelve_candles(self):
        with patch.dict(os.environ, {"BOT_STRATEGY": "bot-Envolvente-BOS"}):
            strategy = create_strategy(BotSettings())
        signal = strategy.evaluate(
            [100.0] * 20 + [102.0],
            hourly_highs=[101.0] * 20 + [102.3],
            hourly_lows=[99.0] * 20 + [100.2],
            hourly_opens=[100.0] * 20 + [100.5],
            hourly_volumes=[100.0] * 8 + [10.0] * 12 + [13.0],
        )
        self.assertEqual(signal.action, "COMPRAR")
        self.assertEqual(strategy.lookback, 12)
        self.assertEqual(strategy.volume_lookback, 12)


if __name__ == "__main__":
    unittest.main()
