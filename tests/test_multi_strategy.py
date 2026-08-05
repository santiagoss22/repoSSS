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

    def test_bullish_engulfing_bos_and_later_retest_buys(self):
        with patch.dict(os.environ, {"BOT_STRATEGY": "bot-Envolvente-BOS"}):
            strategy = create_strategy(BotSettings())
        prices = [100.0] * 13 + [99.5, 100.5]
        opens = [100.0] * 13 + [100.0, 99.4]
        highs = [101.0] * 13 + [100.2, 100.8]
        lows = [99.0] * 13 + [99.3, 99.2]
        armed = strategy.evaluate(
            prices, hourly_highs=highs, hourly_lows=lows, hourly_opens=opens
        )
        self.assertTrue(armed.buy_armed)
        broken = strategy.evaluate(
            prices + [102.0], hourly_highs=highs + [102.3],
            hourly_lows=lows + [100.4], hourly_opens=opens + [100.5]
        )
        self.assertEqual(broken.action, "ESPERAR")
        confirmed = strategy.evaluate(
            prices + [102.0, 101.6], hourly_highs=highs + [102.3, 101.8],
            hourly_lows=lows + [100.4, 100.9],
            hourly_opens=opens + [100.5, 101.4]
        )
        self.assertEqual(confirmed.action, "COMPRAR")

    def test_bearish_engulfing_bos_and_later_retest_sells(self):
        with patch.dict(os.environ, {"BOT_STRATEGY": "bot-Envolvente-BOS"}):
            strategy = create_strategy(BotSettings())
        prices = [100.0] * 13 + [100.5, 99.4]
        opens = [100.0] * 13 + [100.0, 100.6]
        highs = [101.0] * 13 + [100.7, 100.8]
        lows = [99.0] * 13 + [99.8, 99.2]
        strategy.evaluate(
            prices, hourly_highs=highs, hourly_lows=lows, hourly_opens=opens
        )
        strategy.evaluate(
            prices + [98.0], hourly_highs=highs + [99.5],
            hourly_lows=lows + [97.8], hourly_opens=opens + [99.4]
        )
        confirmed = strategy.evaluate(
            prices + [98.0, 98.4], hourly_highs=highs + [99.5, 99.1],
            hourly_lows=lows + [97.8, 98.2],
            hourly_opens=opens + [99.4, 98.6]
        )
        self.assertEqual(confirmed.action, "VENDER")


if __name__ == "__main__":
    unittest.main()
