import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from bitcoin_bot.backtest import run_backtest
from bitcoin_bot.config import BotSettings
from bitcoin_bot.persistence import load_state, save_state
from bitcoin_bot.simulator import (
    MovingAverageStrategy,
    PaperAccount,
    RecoveryController,
    PriceSimulator,
    TrendConfirmation,
)


class PaperAccountTests(unittest.TestCase):
    def test_buy_is_limited_to_ten_percent(self):
        account = PaperAccount(cash_eur=10_000)
        trade = account.buy(price_eur=50_000, value_eur=5_000, reason="prueba")
        self.assertEqual(trade.value_eur, 2_000)
        self.assertAlmostEqual(account.cash_eur, 8_000)
        self.assertAlmostEqual(account.bitcoin, 0.04)

    def test_sell_all_closes_position(self):
        account = PaperAccount(cash_eur=10_000)
        account.buy(price_eur=50_000, value_eur=2_000, reason="prueba")
        account.sell_all(price_eur=55_000, reason="prueba")
        self.assertEqual(account.bitcoin, 0)
        self.assertAlmostEqual(account.cash_eur, 10_200)

    def test_position_limit_blocks_additional_buys(self):
        account = PaperAccount(cash_eur=2_000, bitcoin=0.1)
        self.assertFalse(account.can_buy(price_eur=100_000))

    def test_manual_half_buy_uses_half_of_equity(self):
        account = PaperAccount(cash_eur=10_000)
        trade = account.buy(
            price_eur=50_000,
            value_eur=5_000,
            reason="prueba",
            max_fraction=0.50,
        )
        self.assertEqual(trade.value_eur, 5_000)
        self.assertAlmostEqual(account.bitcoin, 0.1)

    def test_repeated_buys_preserve_two_thousand_euros(self):
        account = PaperAccount(cash_eur=10_000)
        for _ in range(10):
            if account.can_buy(50_000):
                account.buy(50_000, 2_000, "prueba", max_fraction=0.20)
        self.assertGreaterEqual(account.cash_eur, 2_000)
        self.assertFalse(account.can_buy(50_000))

    def test_does_not_buy_when_only_two_hundred_above_reserve(self):
        account = PaperAccount(
            cash_eur=2_200,
            minimum_cash_eur=2_000,
            minimum_trade_eur=500,
        )
        self.assertFalse(account.can_buy(50_000, fee_rate=0.006))
        with self.assertRaises(ValueError):
            account.buy(
                50_000,
                200,
                "demasiado pequeña",
                fee_rate=0.006,
            )

    def test_can_buy_when_minimum_and_fee_fit_above_reserve(self):
        account = PaperAccount(
            cash_eur=2_600,
            minimum_cash_eur=2_000,
            minimum_trade_eur=500,
        )
        self.assertTrue(account.can_buy(50_000, fee_rate=0.006))

    def test_average_cost_includes_fee_and_slippage(self):
        account = PaperAccount(cash_eur=10_000)
        account.buy(
            50_000,
            2_000,
            "prueba",
            fee_rate=0.006,
            slippage_rate=0.001,
        )
        self.assertGreater(account.average_cost_eur, 50_000)
        self.assertGreater(account.total_fees_eur, 0)

    def test_sale_records_realized_profit_after_costs(self):
        account = PaperAccount(cash_eur=10_000)
        account.buy(50_000, 2_000, "prueba", max_fraction=0.20)
        trade = account.sell_all(52_000, "prueba", fee_rate=0.006)
        self.assertGreater(trade.pnl_eur, 0)
        self.assertEqual(account.realized_profit_eur, trade.pnl_eur)

    def test_profitable_lots_are_sold_independently(self):
        account = PaperAccount()
        account.buy(50_000, 2_000, "lote barato")
        account.buy(100_000, 2_000, "lote caro")
        trade = account.sell_profitable_lots(
            55_000,
            0.025,
            "venta por lote",
        )
        self.assertEqual(len(account.lots), 1)
        self.assertAlmostEqual(account.lots[0].cost_basis_eur, 2_000)
        self.assertGreater(trade.pnl_eur, 0)

    def test_frozen_profitable_lot_is_not_sold_in_recovery(self):
        account = PaperAccount()
        account.buy(50_000, 2_000, "lote congelado")
        account.freeze_existing_lots()
        account.buy(60_000, 2_000, "lote operable")
        profitable = account.profitable_lots(
            70_000,
            0.025,
            include_frozen=False,
        )
        self.assertEqual(len(profitable), 1)
        self.assertFalse(profitable[0].frozen)

    def test_drawdown_is_recorded(self):
        account = PaperAccount(cash_eur=2_000, bitcoin=0.1, cost_basis_eur=8_000)
        account.record_equity(80_000)
        drawdown = account.record_equity(60_000)
        self.assertAlmostEqual(drawdown, 0.2)
        self.assertAlmostEqual(account.max_drawdown, 0.2)


class StrategyTests(unittest.TestCase):
    def test_buy_signal_for_falling_prices(self):
        strategy = MovingAverageStrategy(short_window=2, long_window=4)
        self.assertEqual(strategy.signal([13, 12, 10, 9]), "COMPRAR")

    def test_sell_signal_for_rising_prices(self):
        strategy = MovingAverageStrategy(short_window=2, long_window=4)
        self.assertEqual(strategy.signal([10, 10, 12, 13]), "VENDER")

    def test_waits_for_enough_prices(self):
        strategy = MovingAverageStrategy(short_window=2, long_window=4)
        self.assertEqual(strategy.signal([10, 11, 12]), "ESPERAR")


class PriceSimulatorTests(unittest.TestCase):
    def test_seed_produces_repeatable_prices(self):
        first = PriceSimulator(seed=7)
        second = PriceSimulator(seed=7)
        self.assertEqual(first.tick(), second.tick())

    def test_price_never_exceeds_configured_limits(self):
        high = PriceSimulator(initial_price=500_000, seed=1)
        low = PriceSimulator(initial_price=1, seed=2)
        for _ in range(20_000):
            self.assertLessEqual(high.tick(), 200_000)
            self.assertGreaterEqual(low.tick(), 20_000)

    def test_high_price_is_pulled_toward_anchor(self):
        simulator = PriceSimulator(initial_price=190_000, seed=7)
        for _ in range(5_000):
            simulator.tick()
        self.assertLess(simulator.price, 190_000)


class TrendConfirmationTests(unittest.TestCase):
    def test_buy_reference_survives_oscillation(self):
        confirmation = TrendConfirmation(confirmation_ticks=3)
        actions = [
            confirmation.update(price, False)[0]
            for price in [103, 102, 101, 100, 101, 100.5, 99]
        ]
        self.assertEqual(actions[-1], "COMPRAR")


class PersistenceTests(unittest.TestCase):
    def test_state_round_trip(self):
        account = PaperAccount()
        account.buy(50_000, 2_000, "persistencia")
        settings = BotSettings(sell_gain=0.03)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            save_state(path, account, settings)
            loaded_account, loaded_settings = load_state(path)
        self.assertAlmostEqual(loaded_account.bitcoin, account.bitcoin)
        self.assertEqual(len(loaded_account.trades), 1)
        self.assertEqual(loaded_settings.sell_gain, 0.03)


class BacktestTests(unittest.TestCase):
    def test_backtest_returns_metrics(self):
        prices = [
            100, 99, 98, 97, 96, 97, 98, 99, 102, 105,
            104, 103, 102, 101, 100, 101, 104, 108, 112,
        ]
        result = run_backtest(
            prices,
            BotSettings(
                confirmation_ticks=2,
                sell_gain=0.01,
                fee_rate=0.001,
                slippage_rate=0.0,
            ),
        )
        self.assertGreaterEqual(result.trades, 1)
        self.assertGreater(result.ending_equity, 0)
        self.assertAlmostEqual(result.buy_hold_return_percent, 12.0)
        self.assertGreaterEqual(result.winning_sales, 0)
        self.assertGreaterEqual(result.losing_sales, 0)
        self.assertGreaterEqual(result.win_rate_percent, 0)
        self.assertLessEqual(result.win_rate_percent, 100)
        self.assertAlmostEqual(
            result.excess_return_percent,
            result.return_percent - result.buy_hold_return_percent,
        )


class RecoveryModeTests(unittest.TestCase):
    def test_deep_loss_freezes_old_lots_after_stabilization(self):
        account = PaperAccount()
        account.buy(50_000, 2_000, "lote antiguo")
        recovery = RecoveryController(
            loss_trigger=0.10,
            stable_ticks=5,
            stable_range=0.01,
        )
        for price in [44_000, 44_050, 43_980, 44_020, 44_010]:
            status = recovery.update(account, price)
        self.assertTrue(recovery.active)
        self.assertTrue(recovery.enabled)
        self.assertGreater(account.frozen_bitcoin, 0)
        self.assertIn("Recuperación activa", status)

    def test_recovery_sale_leaves_frozen_lot_untouched(self):
        account = PaperAccount()
        account.buy(50_000, 2_000, "lote antiguo")
        account.freeze_existing_lots()
        frozen_amount = account.frozen_bitcoin
        account.buy(44_000, 2_000, "lote recuperación")
        account.sell_tradable(46_000, "venta recuperación")
        self.assertAlmostEqual(account.bitcoin, frozen_amount)
        self.assertAlmostEqual(account.frozen_bitcoin, frozen_amount)
        self.assertEqual(account.tradable_bitcoin, 0)

    def test_recovery_does_not_activate_in_wide_range(self):
        account = PaperAccount()
        account.buy(50_000, 2_000, "lote antiguo")
        recovery = RecoveryController(stable_ticks=5, stable_range=0.01)
        for price in [44_000, 45_000, 43_500, 45_500, 44_200]:
            recovery.update(account, price)
        self.assertTrue(recovery.active)
        self.assertFalse(recovery.enabled)

    def test_sell_reference_survives_oscillation(self):
        confirmation = TrendConfirmation(confirmation_ticks=3)
        actions = [
            confirmation.update(price, True)[0]
            for price in [100, 101, 102, 103, 102, 104, 105.58]
        ]
        self.assertEqual(actions[-1], "VENDER")

    def test_does_not_sell_below_two_point_five_percent_target(self):
        confirmation = TrendConfirmation(confirmation_ticks=3)
        actions = [
            confirmation.update(price, True)[0]
            for price in [100, 101, 102, 103, 104, 105.57]
        ]
        self.assertEqual(actions[-1], "ESPERAR")

    def test_does_not_arm_before_three_cycles(self):
        confirmation = TrendConfirmation(confirmation_ticks=3)
        confirmation.update(100, False)
        confirmation.update(99, False)
        action, status = confirmation.update(98, False)
        self.assertEqual(action, "ESPERAR")
        self.assertIn("2/3", status)

    def test_can_arm_another_buy_while_holding_bitcoin(self):
        confirmation = TrendConfirmation(confirmation_ticks=3)
        actions = [
            confirmation.update(price, True)[0]
            for price in [103, 102, 101, 100, 99]
        ]
        self.assertEqual(actions[-1], "COMPRAR")

    def test_buy_reference_switches_to_sale_after_reversal(self):
        confirmation = TrendConfirmation(
            confirmation_ticks=2,
            reference_expiry_ticks=20,
        )
        for price in [103, 102, 101]:
            confirmation.update(price, True)
        self.assertEqual(confirmation.phase, "COMPRA_ARMADA")
        confirmation.update(102, True)
        action, status = confirmation.update(103, True)
        self.assertEqual(action, "ESPERAR")
        self.assertEqual(confirmation.phase, "VENTA_ARMADA")
        self.assertIn("Tendencia invertida", status)

    def test_sale_reference_switches_to_buy_after_reversal(self):
        confirmation = TrendConfirmation(
            confirmation_ticks=2,
            reference_expiry_ticks=20,
        )
        for price in [100, 101, 102]:
            confirmation.update(price, True)
        self.assertEqual(confirmation.phase, "VENTA_ARMADA")
        confirmation.update(101, True)
        action, status = confirmation.update(100, True)
        self.assertEqual(action, "ESPERAR")
        self.assertEqual(confirmation.phase, "COMPRA_ARMADA")
        self.assertIn("Tendencia invertida", status)

    def test_stale_reference_expires(self):
        confirmation = TrendConfirmation(
            confirmation_ticks=2,
            reference_expiry_ticks=3,
        )
        for price in [103, 102, 101]:
            confirmation.update(price, False)
        self.assertEqual(confirmation.phase, "COMPRA_ARMADA")
        confirmation.update(101.5, False)
        confirmation.update(101.4, False)
        action, status = confirmation.update(101.6, False)
        self.assertEqual(action, "ESPERAR")
        self.assertEqual(confirmation.phase, "ESPERANDO")
        self.assertIn("caducada", status)


if __name__ == "__main__":
    unittest.main()
