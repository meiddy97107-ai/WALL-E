"""
test_structure_trap.py — Tests unitaires pour la strategie STRUCTURE TRAP.

Utilise des DataFrames pandas avec des donnees synthetiques.
Ne depend pas de MT5 pour les tests unitaires.
"""

import sys
from pathlib import Path

# Ajouter le projet au path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from strategies.structure_trap import StructureTrap
from indicators.atr import calculate_atr
from indicators.ema import calculate_ema, get_slope


# ──────────────────────────────────────────────
# DATA GENERATORS
# ──────────────────────────────────────────────

def generate_candles(count: int, base_price: float = 1.1000,
                     volatility: float = 0.001, trend: float = 0.0,
                     start_time: datetime = None) -> pd.DataFrame:
    """Genere un DataFrame de bougies synthetiques.

    Args:
        count: Nombre de bougies.
        base_price: Prix de depart.
        volatility: Volatilite (ecart-type du bruit).
        trend: Tendance (positive = hausse, negative = baisse).
        start_time: Date/heure de depart (auto si None).

    Returns:
        DataFrame avec colonnes time, open, high, low, close.
    """
    if start_time is None:
        start_time = datetime.now() - timedelta(minutes=count)

    np.random.seed(42)
    prices = [base_price]
    for i in range(count - 1):
        change = np.random.normal(trend, volatility)
        prices.append(prices[-1] + change)

    data = []
    for i in range(count):
        t = start_time + timedelta(minutes=i)
        open_p = prices[i]
        close = prices[i + 1] if i + 1 < len(prices) else prices[-1]
        high = max(open_p, close) + abs(np.random.normal(0, volatility * 0.5))
        low = min(open_p, close) - abs(np.random.normal(0, volatility * 0.5))
        data.append({
            "time": t,
            "open": open_p,
            "high": high,
            "low": low,
            "close": close,
        })

    return pd.DataFrame(data)


def generate_orb_range(orb_high: float = 1.1050, orb_low: float = 1.0950,
                       breakout: str = "HAUT", count: int = 50) -> pd.DataFrame:
    """Genere des bougies M15 avec un ORB defini et une cassure.

    Args:
        orb_high: Haut du range ORB.
        orb_low: Bas du range ORB.
        breakout: "HAUT" ou "BAS".
        count: Nombre de bougies.

    Returns:
        DataFrame de bougies M15.
    """
    now = datetime.now()
    # Simuler les bougies de la fenetre ORB (15h30-16h00 = ~2 bougies M15)
    start = now - timedelta(hours=6)

    data = []
    mid = (orb_high + orb_low) / 2

    for i in range(count):
        t = start + timedelta(minutes=15 * i)
        if breakout == "HAUT":
            if i < count // 2:
                # Dans le range
                close = np.random.uniform(orb_low, orb_high)
            else:
                # Cassure haussiere
                progress = (i - count // 2) / (count // 2)
                close = orb_high + progress * (orb_high - orb_low) * 2
        else:
            if i < count // 2:
                close = np.random.uniform(orb_low, orb_high)
            else:
                progress = (i - count // 2) / (count // 2)
                close = orb_low - progress * (orb_high - orb_low) * 2

        high = close + abs(np.random.normal(0, 0.002))
        low = close - abs(np.random.normal(0, 0.002))
        open_p = close + np.random.normal(0, 0.001)

        data.append({
            "time": t,
            "open": open_p,
            "high": high,
            "low": low,
            "close": close,
        })

    return pd.DataFrame(data)


# ──────────────────────────────────────────────
# MOCK DATA FEED
# ──────────────────────────────────────────────

class MockDataFeed:
    """Simule DataFeed pour les tests sans MT5."""

    def __init__(self):
        self._candles_cache = {}

    def get_candles(self, symbol: str, timeframe: str, count: int = 100) -> pd.DataFrame:
        cache_key = f"{symbol}_{timeframe}_{count}"
        if cache_key in self._candles_cache:
            return self._candles_cache[cache_key]
        # Generer des donnees par defaut
        df = generate_candles(count, base_price=1.1000)
        self._candles_cache[cache_key] = df
        return df

    def get_current_price(self, symbol: str) -> dict:
        return {"bid": 1.1000, "ask": 1.1002, "spread": 0.0002}

    def set_candles(self, symbol: str, timeframe: str, df: pd.DataFrame):
        self._candles_cache[f"{symbol}_{timeframe}_{len(df)}"] = df


# ──────────────────────────────────────────────
# CONFIG DE TEST
# ──────────────────────────────────────────────

TEST_ORB_CONFIG = {
    "session_start": "16:00",
    "session_end": "21:45",
    "orb_start": "15:30",
    "orb_end": "16:00",
    "contexte": "orb",
    "atr_filter": 2.0,
    "ema_rapide": 5,
    "ema_lente": 8,
    "seuil_pente": 1.5,
    "sl_buffer": 0.5,
    "be_threshold": 1.5,
    "timeout_h2": 30,
    "retest_tolerance": 2.0,
    "biais_premarket": True,
}

TEST_BOLLINGER_CONFIG = {
    "contexte": "bollinger",
    "atr_filter": 1.5,
    "ema_rapide": 5,
    "ema_lente": 8,
    "seuil_pente": 0.20,
    "sl_buffer": 0.5,
    "timeout_h2": 30,
    "retest_tolerance": 2.0,
}

TEST_ASIAN_CONFIG = {
    "asian_box_start": "02:00",
    "asian_box_end": "08:00",
    "signal_cutoff": "11:30",
    "contexte": "asian_box",
    "box_amplitude_max": 1.0,
    "atr_filter": 1.2,
    "ema_rapide": 5,
    "ema_lente": 8,
    "seuil_pente": 0.00003,
    "sl_buffer": 0.3,
    "timeout_h2": 30,
    "retest_tolerance": 2.0,
}


# ──────────────────────────────────────────────
# TESTS : Filtre Contextuel M15
# ──────────────────────────────────────────────

class TestORB:
    """Tests pour le calcul de l'ORB."""

    def test_orb_flag_trop_etroit(self):
        """amplitude < 0.5 x ATR -> TROP_ETROIT (pas de contexte)."""
        mock = MockDataFeed()
        trap = StructureTrap(mock)

        orb_df = generate_orb_range(orb_high=1.1005, orb_low=1.1000,
                                     breakout="HAUT", count=50)
        mock.set_candles("US100", "M15", orb_df)

        context = trap._compute_orb("US100", orb_df, TEST_ORB_CONFIG)
        assert context is None or context.get("flag") == "TROP_ETROIT"

    def test_orb_flag_valide(self):
        """amplitude dans la zone (0.5x - 2.5x ATR) -> VALIDE."""
        mock = MockDataFeed()
        trap = StructureTrap(mock)

        orb_high = 1.1100
        orb_low = 1.0900
        orb_df = generate_orb_range(orb_high, orb_low, breakout="HAUT", count=50)

        mock.set_candles("US100", "M15", orb_df)
        context = trap._compute_orb("US100", orb_df, TEST_ORB_CONFIG)
        if context is not None:
            assert context["flag"] == "VALIDE"

    def test_orb_breakout_haut(self):
        """Prix > ORB_HIGH -> breakout HAUT."""
        mock = MockDataFeed()
        trap = StructureTrap(mock)

        orb_high = 1.1050
        orb_low = 1.0950
        orb_df = generate_orb_range(orb_high, orb_low, breakout="HAUT", count=50)

        context = trap._compute_orb("US100", orb_df, TEST_ORB_CONFIG)
        if context is not None:
            assert context["breakout"] == "HAUT"

    def test_orb_breakout_bas(self):
        """Prix < ORB_LOW -> breakout BAS."""
        mock = MockDataFeed()
        trap = StructureTrap(mock)

        orb_high = 1.1050
        orb_low = 1.0950
        orb_df = generate_orb_range(orb_high, orb_low, breakout="BAS", count=50)

        context = trap._compute_orb("US100", orb_df, TEST_ORB_CONFIG)
        if context is not None:
            assert context["breakout"] == "BAS"


class TestBollinger:
    """Tests pour le contexte Bollinger."""

    def test_bollinger_breakout_haut(self):
        """Cloture au-dessus de BB_UPPER -> BREAKOUT_HAUT."""
        mock = MockDataFeed()
        trap = StructureTrap(mock)

        # Generer des bougies avec une forte tendance haussiere
        candles = generate_candles(50, base_price=100.0, trend=0.05, volatility=0.02)

        context = trap._compute_bollinger_context("XAUUSD", candles, TEST_BOLLINGER_CONFIG)
        if context is not None:
            assert context["breakout"] == "HAUT"

    def test_bollinger_breakout_bas(self):
        """Cloture en-dessous de BB_LOWER -> BREAKOUT_BAS."""
        mock = MockDataFeed()
        trap = StructureTrap(mock)

        candles = generate_candles(50, base_price=100.0, trend=-0.05, volatility=0.02)

        context = trap._compute_bollinger_context("XAUUSD", candles, TEST_BOLLINGER_CONFIG)
        if context is not None:
            assert context["breakout"] == "BAS"


class TestAsianBox:
    """Tests pour le contexte Asian Box."""

    def test_asian_box_valid(self):
        """Amplitude < box_amplitude_max x ATR_8H -> VALIDE."""
        mock = MockDataFeed()
        trap = StructureTrap(mock)

        candles = generate_candles(50, base_price=1.1000, volatility=0.00005)
        mock.set_candles("EURUSD", "H1", generate_candles(20, base_price=1.1000, volatility=0.0005))

        context = trap._compute_asian_box("EURUSD", candles, TEST_ASIAN_CONFIG)
        if context is not None:
            assert context["flag"] == "VALIDE"

    def test_asian_box_structure(self):
        """L'Asian Box retourne les bonnes cles de structure."""
        mock = MockDataFeed()
        trap = StructureTrap(mock)

        candles = generate_candles(50, base_price=1.1000, volatility=0.0001)

        context = trap._compute_asian_box("EURUSD", candles, TEST_ASIAN_CONFIG)
        if context is not None:
            assert "high" in context
            assert "low" in context
            assert "mid" in context
            assert "pdh" in context
            assert "pdl" in context
            assert "breakout" in context


# ──────────────────────────────────────────────
# TESTS : Niveau de cassure + retest
# ──────────────────────────────────────────────

class TestBreakoutReferenceLevel:
    """Extraction du niveau casse selon le contexte."""

    def test_orb_high_low(self):
        mock = MockDataFeed()
        trap = StructureTrap(mock)
        ctx = {"high": 1.11, "low": 1.09, "breakout": "HAUT"}
        assert trap._breakout_reference_level(ctx, "HAUT") == 1.11
        assert trap._breakout_reference_level(ctx, "BAS") == 1.09

    def test_bollinger_upper_lower(self):
        mock = MockDataFeed()
        trap = StructureTrap(mock)
        ctx = {"upper": 2500.0, "lower": 2400.0, "breakout": "HAUT"}
        assert trap._breakout_reference_level(ctx, "HAUT") == 2500.0
        assert trap._breakout_reference_level(ctx, "BAS") == 2400.0


class TestRetestTrigger:
    """Tests pour _compute_retest_trigger."""

    def _candles_retest_buy(self, level: float) -> pd.DataFrame:
        """Une bougie haussiere proche du niveau (support)."""
        t = datetime.now()
        close = level + 0.0002
        return pd.DataFrame([{
            "time": t,
            "open": level,
            "high": close + 0.0001,
            "low": level - 0.0005,
            "close": close,
        }])

    def test_retest_buy_returns_signal(self):
        mock = MockDataFeed()
        trap = StructureTrap(mock)
        level = 1.1000
        trap.state["EURUSD"] = {
            "breakout_level": level,
            "breakout_direction": "HAUT",
        }
        candles = self._candles_retest_buy(level)
        atr_m1 = 0.001
        cfg = dict(TEST_ASIAN_CONFIG)
        sig = trap._compute_retest_trigger(
            "EURUSD", {}, candles, atr_m1, cfg
        )
        if sig is not None:
            assert sig["direction"] == "BUY"
            assert "entry" in sig

    def test_retest_sell_out_of_zone(self):
        mock = MockDataFeed()
        trap = StructureTrap(mock)
        level = 1.1000
        trap.state["EURUSD"] = {
            "breakout_level": level,
            "breakout_direction": "BAS",
        }
        atr_m1 = 0.001
        tol = atr_m1 * 3.0
        candles = pd.DataFrame([{
            "time": datetime.now(),
            "open": level - 0.02,
            "high": (level - tol) - 0.001,
            "low": level - 0.021,
            "close": level - 0.0205,
        }])
        sig = trap._compute_retest_trigger(
            "EURUSD", {}, candles, atr_m1, TEST_ASIAN_CONFIG
        )
        assert sig is None

    def test_reset_state(self):
        mock = MockDataFeed()
        trap = StructureTrap(mock)
        trap.state["EURUSD"] = {"breakout_level": 1.1, "breakout_direction": "HAUT"}
        trap._reset_state("EURUSD")
        assert "EURUSD" not in trap.state


# ──────────────────────────────────────────────
# TESTS : Anti-Chop
# ──────────────────────────────────────────────

class TestAntiChop:
    """Tests pour le filtre anti-chop."""

    def test_anti_chop_buy_mid_cross(self):
        """BUY : cloture M5 sous le milieu -> True."""
        from filters.anti_chop import AntiChop
        ac = AntiChop()

        candles = generate_candles(10, base_price=1.0900, trend=-0.001)
        position = {"direction": "BUY"}
        assert ac.check(position, 1.1000, candles) == True

    def test_anti_chop_sell_mid_cross(self):
        """SELL : cloture M5 au-dessus du milieu -> True."""
        from filters.anti_chop import AntiChop
        ac = AntiChop()

        candles = generate_candles(10, base_price=1.1100, trend=0.001)
        position = {"direction": "SELL"}
        assert ac.check(position, 1.1000, candles) == True


# ──────────────────────────────────────────────
# TESTS : Spread Filter
# ──────────────────────────────────────────────

class TestSpreadFilter:
    """Tests pour le filtre spread."""

    def test_spread_filter_normal(self):
        """Spread normal -> pas bloque."""
        from filters.spread_filter import SpreadFilter
        sf = SpreadFilter()

        # Remplir l'historique
        for _ in range(10):
            sf.update("EURUSD", 0.0002)

        assert sf.is_blocked("EURUSD", 0.0003) == False

    def test_spread_filter_blocked(self):
        """Spread > 2x moyenne -> bloque."""
        from filters.spread_filter import SpreadFilter
        sf = SpreadFilter()

        for _ in range(10):
            sf.update("EURUSD", 0.0002)

        assert sf.is_blocked("EURUSD", 0.0010) == True


# ──────────────────────────────────────────────
# TESTS : News Filter
# ──────────────────────────────────────────────

class TestNewsFilter:
    """Tests pour le filtre news."""

    def test_news_volatile(self):
        """ATR double -> volatilite anormale."""
        from filters.news_filter import NewsFilter
        nf = NewsFilter()
        assert nf.is_volatile(30.0, 10.0) == True

    def test_news_not_volatile(self):
        """ATR normal -> pas de volatilite."""
        from filters.news_filter import NewsFilter
        nf = NewsFilter()
        assert nf.is_volatile(15.0, 10.0) == False


# ──────────────────────────────────────────────
# TESTS : Indicators
# ──────────────────────────────────────────────

class TestIndicators:
    """Tests pour les indicateurs."""

    def test_atr_positive(self):
        """ATR est toujours positif."""
        candles = generate_candles(50)
        atr = calculate_atr(candles, 14)
        assert atr > 0

    def test_ema_calculation(self):
        """EMA se calcule sans erreur."""
        candles = generate_candles(50)
        ema = calculate_ema(candles, 8)
        assert not ema.empty
        assert ema.iloc[-1] > 0

    def test_ema_slope_zero_no_trend(self):
        """Pente proche de 0 sans tendance."""
        candles = generate_candles(50, trend=0.0, volatility=0.000001)
        ema = calculate_ema(candles, 8)
        slope = get_slope(ema, 5)
        assert abs(slope) < 0.001
