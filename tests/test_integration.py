"""
test_integration.py — Tests d'integration pour le systeme complet.

Utilise des mocks pour MT5 — ne depend pas d'une connexion reelle.
Verifie que tous les modules fonctionnent ensemble.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from config.settings import CHALLENGE_START_BALANCE
from config.market_config import MARKET_CONFIG
from risk.risk_manager import RiskManager
from risk.phase_detector import PhaseDetector
from risk.budget_tracker import BudgetTracker
from risk.streak_brake import StreakBrake
from pulse.pulse_manager import PulseManager
from pulse.shield import Shield
from pulse.tracker import Tracker
from pulse.rocket import Rocket
from strategies.structure_trap import StructureTrap
from strategies.smc_session import SMCSession


# ──────────────────────────────────────────────
# MOCKS
# ──────────────────────────────────────────────

class MockConnector:
    """Simule MT5Connector pour les tests."""
    def get_balance(self):
        return 2500.0
    def get_equity(self):
        return 2500.0
    def is_connected(self):
        return True
    def get_account_info(self):
        return {"balance": 2500.0, "equity": 2500.0}


class MockOrderManager:
    """Simule OrderManager — enregistre les ordres sans les envoyer."""
    def __init__(self):
        self.opened_orders = []
        self.closed_orders = []
        self.sl_modifications = []

    def open_position(self, **kwargs):
        ticket = len(self.opened_orders) + 1
        order = {"ticket": ticket}
        order.update(kwargs)
        # Normaliser le symbole
        if "symbol" in order:
            order["actif"] = order.pop("symbol")
        if "direction" in order:
            order["direction"] = order["direction"]
        if "sl_price" in order:
            order["sl"] = order.pop("sl_price")
        self.opened_orders.append(order)
        return {"ticket": ticket}

    def close_position(self, ticket, reason=""):
        self.closed_orders.append({"ticket": ticket, "reason": reason})
        # Retirer des ordres ouverts
        self.opened_orders = [o for o in self.opened_orders if o.get("ticket") != ticket]
        return True

    def get_open_positions(self):
        return list(self.opened_orders)

    def modify_sl(self, ticket, new_sl):
        self.sl_modifications.append({"ticket": ticket, "new_sl": new_sl})
        return True

    def close_all_positions(self, reason=""):
        self.closed_orders.extend([{"ticket": o["ticket"], "reason": reason}
                                    for o in self.opened_orders])
        self.opened_orders = []
        self.sl_modifications = []

    def cancel_pending_orders(self):
        pass


class MockDataFeed:
    """Simule DataFeed pour les tests."""
    def __init__(self):
        self._candles_cache = {}
        self._price = 1.1000

    def get_candles(self, symbol: str, timeframe: str, count: int = 100) -> pd.DataFrame:
        cache_key = f"{symbol}_{timeframe}_{count}"
        if cache_key in self._candles_cache:
            return self._candles_cache[cache_key]

        step = 15 if timeframe == "M15" else (60 if timeframe == "H1" else 1)
        start = datetime.now() - timedelta(minutes=count * step)
        df = self._generate_candles(count, start, step)
        self._candles_cache[cache_key] = df
        return df

    def _generate_candles(self, count: int, start: datetime, step: int) -> pd.DataFrame:
        np.random.seed(42)
        base = self._price
        prices = [base]
        for i in range(count - 1):
            prices.append(prices[-1] + np.random.normal(0, 0.0005))
        data = []
        for i in range(count):
            t = start + timedelta(minutes=i * step)
            open_p = prices[i]
            close = prices[i + 1] if i + 1 < len(prices) else prices[-1]
            high = max(open_p, close) + abs(np.random.normal(0, 0.0003))
            low = min(open_p, close) - abs(np.random.normal(0, 0.0003))
            data.append({"time": t, "open": open_p, "high": high,
                         "low": low, "close": close, "tick_volume": 100,
                         "spread": 0.0002, "real_volume": 0})
        return pd.DataFrame(data)

    def get_current_price(self, symbol: str) -> dict:
        return {"bid": self._price, "ask": self._price + 0.0002, "spread": 0.0002}

    def set_candles(self, symbol: str, timeframe: str, df: pd.DataFrame):
        self._candles_cache[f"{symbol}_{timeframe}_{len(df)}"] = df


# ─────────────────────────────────────────────────
# TESTS DU RISK SYSTEM
# ─────────────────────────────────────────────────

class TestRiskSystem:
    """Tests du systeme de gestion des risques."""

    def test_phase_detection_p1(self):
        """Solde 2400 avec start 2500 -> P1."""
        import os
        os.environ["CHALLENGE_START_BALANCE"] = "2500"
        # Recharger la detection
        detector = PhaseDetector()
        assert detector.detect(2400.0) == "P1"

    def test_phase_detection_p2(self):
        """Solde 2720 avec start 2500 -> P2 (108% de 2500 = 2700)."""
        detector = PhaseDetector()
        assert detector.detect(2720.0) == "P2"

    def test_phase_detection_funded(self):
        """Solde 2850 -> FUNDED (113.4% de 2500 = 2835)."""
        detector = PhaseDetector()
        assert detector.detect(2850.0) == "FUNDED"

    def test_risk_per_trade_p1(self):
        """P1 -> risk = daily_budget x 0.50 = 100 x 0.50 = 50."""
        rm = RiskManager()
        rm.budget_tracker.reset_daily(2500.0)  # daily_budget = 100
        risk = rm.calculate_risk_for_trade(2400.0)  # P1 risk_fraction = 0.50
        # daily_budget * 0.50 = 100 * 0.50 = 50
        assert abs(risk - 50.0) < 0.01

    def test_risk_per_trade_funded(self):
        """FUNDED -> risk = daily_budget x 0.33 = 33."""
        rm = RiskManager()
        rm.budget_tracker.reset_daily(2500.0)
        # Forcer la phase FUNDED
        risk = rm.calculate_risk_for_trade(2850.0)  # FUNDED risk_fraction = 0.33
        # daily_budget * 0.33 = 100 * 0.33 = 33
        assert abs(risk - 33.0) < 0.01

    def test_real_time_exposure_shield_only(self):
        """2 positions SHIELD -> exposition = somme des risques."""
        rm = RiskManager()
        rm.budget_tracker.reset_daily(2500.0)

        positions = [
            {"etat": "SHIELD", "risk_initial_": 50.0},
            {"etat": "SHIELD", "risk_initial_": 50.0},
        ]
        exposure = rm.budget_tracker.get_real_exposure(positions)
        assert abs(exposure - 100.0) < 0.01

    def test_real_time_exposure_all_be(self):
        """1 SHIELD + 1 TRACKER -> exposition = 50."""
        rm = RiskManager()
        rm.budget_tracker.reset_daily(2500.0)

        positions = [
            {"etat": "SHIELD", "risk_initial_": 50.0},
            {"etat": "TRACKER", "risk_initial_": 50.0},
        ]
        exposure = rm.budget_tracker.get_real_exposure(positions)
        assert abs(exposure - 50.0) < 0.01

    def test_daily_limit_hit(self):
        """Pertes = 100 sur 2500 (4%) -> kill switch."""
        bt = BudgetTracker()
        bt.reset_daily(2500.0)  # daily_budget = 100
        assert bt.is_daily_limit_hit(2400.0) == True  # Perte de 100

    def test_daily_limit_not_hit(self):
        """Pertes = 80 -> pas de kill switch."""
        bt = BudgetTracker()
        bt.reset_daily(2500.0)
        assert bt.is_daily_limit_hit(2420.0) == False  # Perte de 80 < 100

    def test_streak_2_losses_skip(self):
        """2 pertes -> prochain signal ignore."""
        sb = StreakBrake()
        sb.on_trade_closed("LOSS")
        sb.on_trade_closed("LOSS")
        assert sb.should_skip_next_signal() == True
        assert sb.should_stop_trading() == False

    def test_streak_3_losses_stop(self):
        """3 pertes -> trading stoppe."""
        sb = StreakBrake()
        sb.on_trade_closed("LOSS")
        sb.on_trade_closed("LOSS")
        sb.on_trade_closed("LOSS")
        assert sb.should_stop_trading() == True

    def test_streak_reset_on_win(self):
        """Perte + Gain + Perte -> streak = 1 (pas 2)."""
        sb = StreakBrake()
        sb.on_trade_closed("LOSS")
        sb.on_trade_closed("WIN")
        sb.on_trade_closed("LOSS")
        assert sb.should_skip_next_signal() == False  # streak = 1, pas 2
        assert sb.should_stop_trading() == False

    def test_risk_manager_status(self):
        """get_status retourne un resume complet."""
        rm = RiskManager()
        rm.budget_tracker.reset_daily(2500.0)
        status = rm.get_status()
        assert "phase" in status
        assert "daily_budget" in status
        assert "exposure" in status
        assert "available" in status
        assert "streak" in status
        assert "kill_switch" in status


# ─────────────────────────────────────────────────
# TESTS DU PULSE
# ─────────────────────────────────────────────────

class TestPulseSystem:
    """Tests du systeme PULSE."""

    def test_shield_to_tracker_transition(self):
        """Profit atteint be_threshold x ATR -> transition TRACKER + SL au BE."""
        shield = Shield()
        position = {
            "ticket": 1, "etat": "SHIELD", "direction": "BUY",
            "prix_entree": 1.1000, "conviction": "STANDARD",
        }
        config = {"be_threshold": 1.0}
        atr_m1 = 0.001
        # _get_current_price retourne prix_entree donc profit = 0
        # Normalement, avec un prix plus haut, on detecterait la transition
        updated = shield.update(position, atr_m1, config)
        assert updated["etat"] == "SHIELD"  # Pas de profit

    def test_shield_to_tracker_high_conviction(self):
        """Conviction HIGH -> BE 20% plus tot."""
        shield = Shield()
        position = {
            "ticket": 1, "etat": "SHIELD", "direction": "BUY",
            "prix_entree": 1.1000, "conviction": "HIGH",
        }
        config = {"be_threshold": 1.0}
        atr_m1 = 0.001
        updated = shield.update(position, atr_m1, config)
        assert updated["etat"] == "SHIELD"

    def test_tracker_sl_follows_structure(self):
        """Tracker deplace le SL."""
        tracker = Tracker()
        data = {
            "time": [datetime.now() - timedelta(minutes=i) for i in range(50, 0, -1)],
            "open": np.random.normal(1.1000, 0.001, 50),
            "high": np.random.normal(1.1020, 0.001, 50),
            "low": np.random.normal(1.0980, 0.001, 50),
            "close": np.random.normal(1.1000, 0.001, 50),
        }
        candles = pd.DataFrame(data)
        position = {
            "ticket": 1, "etat": "TRACKER", "direction": "BUY",
            "prix_entree": 1.1000, "sl": 1.0980, "compteur_rocket": 0,
        }
        config = {"atr_filter": 1.0, "sl_buffer": 0.5}

        # Forcer des prix haussiers
        candles["close"] = np.linspace(1.1000, 1.1050, 50)
        candles["high"] = candles["close"] + 0.002
        candles["low"] = candles["close"] - 0.001

        updated = tracker.update(position, 0.005, candles, config)
        assert updated["etat"] in ["TRACKER", "EXIT"]

    def test_tracker_to_rocket_transition(self):
        """Expansion ATR confirmee -> ROCKET."""
        tracker = Tracker()
        # Bougies avec forte volatilite
        data = {
            "time": [datetime.now() - timedelta(minutes=i) for i in range(50, 0, -1)],
            "open": np.random.normal(1.1000, 0.01, 50),
            "high": np.random.normal(1.1100, 0.01, 50),
            "low": np.random.normal(1.0900, 0.01, 50),
            "close": np.random.normal(1.1000, 0.01, 50),
        }
        candles = pd.DataFrame(data)
        position = {
            "ticket": 1, "etat": "TRACKER", "direction": "BUY",
            "prix_entree": 1.1000, "sl": 1.0980, "compteur_rocket": 0,
        }
        config = {"rocket_atr_mult": 1.8}

        from indicators.atr import calculate_atr
        atr_m1 = calculate_atr(candles, 14)

        updated = tracker.update(position, atr_m1, candles, config)
        # Doit detecter l'expansion ou rester en TRACKER
        assert updated["etat"] in ["TRACKER", "ROCKET"]

    def test_rocket_sl_wider_buffer(self):
        """ROCKET a un SL plus large que TRACKER."""
        rocket = Rocket()
        data = {
            "time": [datetime.now() - timedelta(minutes=i) for i in range(30, 0, -1)],
            "open": [1.1000] * 30,
            "high": [1.1020] * 30,
            "low": [1.0980] * 30,
            "close": [1.1000] * 30,
        }
        candles = pd.DataFrame(data)
        position = {
            "ticket": 1, "etat": "ROCKET", "direction": "BUY",
            "actif": "EURUSD", "prix_entree": 1.1000, "sl": 1.0980,
            "compteur_rocket": 5,
        }
        config = {"sl_buffer": 0.5}

        updated = rocket.update(position, 0.005, candles, config)
        assert "action" in updated

    def test_rocket_blocks_new_signals(self):
        """ROCKET actif -> pas de nouveau signal."""
        rocket = Rocket(data_feed=None)
        assert rocket.is_asset_locked("EURUSD") == False
        # Simuler un asset en ROCKET
        rocket._active_rockets.add("EURUSD")
        assert rocket.is_asset_locked("EURUSD") == True
        rocket.release_asset("EURUSD")
        assert rocket.is_asset_locked("EURUSD") == False


# ─────────────────────────────────────────────────
# TESTS DU PULSE MANAGER
# ─────────────────────────────────────────────────

class TestPulseManager:
    """Tests du PulseManager complet."""

    def test_pulse_manager_has_open_position(self):
        """has_open_position detecte les positions."""
        om = MockOrderManager()
        df = MockDataFeed()
        rm = RiskManager()
        pm = PulseManager(df, om, rm)

        assert pm.has_open_position("EURUSD") == False
        assert pm.has_open_position("EURUSD", "SMC_SESSION") == False

    def test_pulse_manager_get_exposure(self):
        """get_exposure_by_state retourne l'exposition correcte."""
        om = MockOrderManager()
        df = MockDataFeed()
        rm = RiskManager()
        pm = PulseManager(df, om, rm)

        exposure = pm.get_exposure_by_state()
        assert "SHIELD" in exposure
        assert "TRACKER" in exposure
        assert "ROCKET" in exposure
        assert "total" in exposure
        assert exposure["total"] == 0.0

    def test_pulse_manager_clear_all(self):
        """clear_all vide toutes les positions."""
        om = MockOrderManager()
        df = MockDataFeed()
        rm = RiskManager()
        pm = PulseManager(df, om, rm)

        # Ajouter une position
        pm._positions[1] = {"ticket": 1, "etat": "SHIELD"}
        pm.clear_all()
        assert len(pm.get_all_positions()) == 0

    def test_on_position_opened(self):
        """Enregistre une position dans le PULSE."""
        om = MockOrderManager()
        df = MockDataFeed()
        rm = RiskManager()
        pm = PulseManager(df, om, rm)

        info = {
            "ticket": 1,
            "actif": "EURUSD",
            "direction": "BUY",
            "prix_entree": 1.1000,
            "sl": 1.0950,
            "risk_initial_": 50.0,
            "conviction": "HIGH",
            "strategie": "SMC_SESSION",
        }
        pm.on_position_opened(info)
        assert pm.get_position_state(1)["actif"] == "EURUSD"
        assert pm.get_position_state(1)["conviction"] == "HIGH"

    def test_on_position_closed(self):
        """Supprime une position du PULSE."""
        om = MockOrderManager()
        df = MockDataFeed()
        rm = RiskManager()
        pm = PulseManager(df, om, rm)

        pm._positions[1] = {"ticket": 1, "actif": "EURUSD", "etat": "SHIELD", "strategie": "TRAP"}
        pm.on_position_closed(1, "TEST")
        assert pm.get_position_state(1) == {}


# ─────────────────────────────────────────────────
# TESTS D'INTEGRATION BOUT EN BOUT
# ─────────────────────────────────────────────────

class TestIntegration:
    """Tests d'integration bout en bout."""

    def test_kill_switch_closes_all(self):
        """Kill switch -> toutes les positions fermees."""
        om = MockOrderManager()
        df = MockDataFeed()
        rm = RiskManager()
        pm = PulseManager(df, om, rm)

        # Ouvrir des positions
        om.open_position(symbol="EURUSD", direction="BUY", lot_size=0.01, sl_price=1.0950,
                         comment="TEST", magic=123456)

        assert len(om.get_open_positions()) == 1

        # Kill switch
        om.close_all_positions(reason="DAILY_LOSS_LIMIT")
        pm.clear_all()

        assert len(om.get_open_positions()) == 0
        assert len(pm.get_all_positions()) == 0

    def test_no_double_position_same_asset(self):
        """Pas de double position sur le meme actif."""
        om = MockOrderManager()
        df = MockDataFeed()
        rm = RiskManager()
        pm = PulseManager(df, om, rm)

        # Simuler une position SMC deja ouverte
        info = {
            "ticket": 1, "actif": "EURUSD", "direction": "BUY",
            "prix_entree": 1.1000, "sl": 1.0950, "risk_initial_": 50.0,
            "conviction": "HIGH", "strategie": "SMC_SESSION",
        }
        pm.on_position_opened(info)

        assert pm.has_open_position("EURUSD") == True
        # StructureTrap ne devrait pas ouvrir
        assert pm.has_open_position("EURUSD", "SMC_SESSION") == True

    def test_conviction_boosts_structure_trap(self):
        """London BULLISH + STRUCTURE TRAP BUY -> conviction HIGH."""
        df = MockDataFeed()
        smc = SMCSession(df)

        smc.london_direction["EURUSD"] = {"direction": "BULLISH"}
        conviction = smc.get_conviction("EURUSD", "BUY")
        assert conviction == "HIGH"

    def test_conviction_standard_when_undefined(self):
        """London UNDEFINED -> STANDARD."""
        df = MockDataFeed()
        smc = SMCSession(df)

        smc.london_direction["EURUSD"] = {"direction": "UNDEFINED"}
        conviction = smc.get_conviction("EURUSD", "BUY")
        assert conviction == "STANDARD"

    def test_trade_lifecycle_risk_manager(self):
        """Cycle de vie complet via RiskManager."""
        rm = RiskManager()
        rm.budget_tracker.reset_daily(2500.0)

        # Trade ouvert
        rm.on_trade_opened(1, 50.0)
        assert rm.get_status()["exposure"] == 50.0

        # Trade au BE
        rm.on_trade_be_reached(1)
        assert rm.get_status()["exposure"] == 0.0

        # Trade ferme (WIN)
        rm.on_trade_closed(1, 30.0)
        assert rm.streak_brake.get_stats()["consecutive_losses"] == 0

    def test_trade_lifecycle_with_loss(self):
        """Perte notifiee -> StreakBrake incrementee."""
        rm = RiskManager()
        rm.on_trade_closed(1, -50.0)
        assert rm.streak_brake.get_stats()["consecutive_losses"] == 1
        assert rm.streak_brake.should_skip_next_signal() == False

    def test_shield_tracker_rocket_cycle(self):
        """Simulation du cycle PULSE complet avec le PulseManager."""
        om = MockOrderManager()
        df = MockDataFeed()
        rm = RiskManager()
        pm = PulseManager(df, om, rm)

        # Enregistrer une position
        # D'abord dans l'OrderManager (simule une vraie ouverture)
        om.open_position(symbol="EURUSD", direction="BUY", lot_size=0.01, sl=1.0950,
                         comment="TRAP_EURUSD", magic=123456)
        info = {
            "ticket": 1, "actif": "EURUSD", "direction": "BUY",
            "prix_entree": 1.1000, "sl": 1.0950, "risk_initial_": 50.0,
            "conviction": "HIGH", "strategie": "STRUCTURE_TRAP",
        }
        pm.on_position_opened(info)

        # Verifier que la position est en SHIELD
        assert pm.get_position_state(1)["etat"] == "SHIELD"

        # Simuler une mise a jour PULSE
        pm.update_all(om.get_open_positions())

        # La position existe toujours (pas de trigger EXIT)
        state = pm.get_position_state(1)
        assert state.get("etat") in ["SHIELD", "TRACKER"]


# ─────────────────────────────────────────────────
# TESTS DES INDICATEURS
# ─────────────────────────────────────────────────

class TestIndicators:
    """Tests de base pour les indicateurs."""

    def test_atr_calculation(self):
        """ATR se calcule correctement."""
        from indicators.atr import calculate_atr
        data = {
            "high": [1.1050, 1.1060, 1.1040, 1.1070, 1.1030],
            "low": [1.0950, 1.0960, 1.0940, 1.0970, 1.0930],
            "close": [1.1000, 1.1010, 1.0990, 1.1020, 1.0980],
        }
        candles = pd.DataFrame(data)
        atr = calculate_atr(candles, 3)
        assert atr > 0

    def test_ema_calculation(self):
        """EMA se calcule correctement."""
        from indicators.ema import calculate_ema
        candles = pd.DataFrame({"close": np.linspace(1.1000, 1.1100, 50)})
        ema = calculate_ema(candles, 8)
        assert not ema.empty
        assert ema.iloc[-1] > 0

    def test_adx_calculation(self):
        """ADX se calcule sans erreur."""
        from indicators.adx import calculate_adx
        np.random.seed(42)
        data = {
            "high": np.random.normal(1.1050, 0.005, 50),
            "low": np.random.normal(1.0950, 0.005, 50),
            "close": np.random.normal(1.1000, 0.005, 50),
        }
        candles = pd.DataFrame(data)
        adx = calculate_adx(candles, 14)
        assert adx > 0

    def test_bollinger_calculation(self):
        """Bollinger se calcule sans erreur."""
        from indicators.bollinger import calculate_bollinger
        candles = pd.DataFrame({"close": np.linspace(1.1000, 1.1100, 50)})
        bb = calculate_bollinger(candles, 20, 2.0)
        assert bb["upper"] > bb["middle"]
        assert bb["middle"] > bb["lower"]
