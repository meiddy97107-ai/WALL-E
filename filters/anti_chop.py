"""
anti_chop.py — Anti-chop base sur M5.

Detecte les conditions de marche non-directionnel (chop/range)
et bloque les nouveaux trades pour eviter de se faire pieger.

Fonction check() utilisee par le PulseManager pour couper les trades
quand le prix revient dans le range de reference (ORB_MID, ASIAN_MID, BB_MIDDLE).
"""

import pandas as pd

from indicators.adx import calculate_adx
from utils.logger import get_logger

logger = get_logger("anti_chop")


class AntiChop:
    """Detecte les marches en chop et filtre les signaux.

    Utilise l'ADX et la compacite des bougies M5 pour determiner
    si le marche est directionnel ou non.
    """

    def __init__(self):
        self._adx_threshold = 20  # ADX < 20 = chop
        self._min_directional_candles = 3

    def is_chop(self, candles_m5: pd.DataFrame) -> bool:
        """Verifie si le marche est en condition de chop.

        Criteres :
        1. ADX < 20 (pas de tendance)
        2. Bougies longues ET alternees
        3. Ratio range/ATR faible

        Args:
            candles_m5: DataFrame des bougies M5.

        Returns:
            True si le marche est en chop.
        """
        if candles_m5.empty or len(candles_m5) < 20:
            return False

        adx = calculate_adx(candles_m5, 14)
        if adx >= self._adx_threshold:
            return False

        if not self._is_choppy_candles(candles_m5):
            return False

        logger.debug(f"Marche en chop detecte (ADX={adx:.1f})")
        return True

    def is_directional(self, candles_m5: pd.DataFrame) -> bool:
        """Verifie si le marche est directionnel (inverse de chop)."""
        return not self.is_chop(candles_m5) and self._has_momentum(candles_m5)

    def should_block_trade(self, candles_m5: pd.DataFrame) -> bool:
        """Blocage d'entree si marche en chop."""
        if self.is_chop(candles_m5):
            logger.warning("Trade bloque par le filtre anti-chop.")
            return True
        return False

    def check(self, position: dict, reference_mid: float,
              candles_m5: pd.DataFrame) -> bool:
        """Verifie si un trade actif doit etre coupe par l'anti-chop.

        Appele par le PulseManager a chaque mise a jour des positions.

        Si une bougie M5 cloture au-dela du milieu du range de reference
        (ORB_MID, ASIAN_MID, ou BB_MIDDLE) dans le sens oppose au trade
        -> signal de sortie.

        Args:
            position: Dict de la position (contient "direction").
            reference_mid: Prix milieu du range de reference.
            candles_m5: DataFrame M5.

        Returns:
            True si le trade doit etre coupe.
        """
        if candles_m5.empty or reference_mid is None or reference_mid == 0:
            return False

        last_close = float(candles_m5["close"].iloc[-1])
        direction = position.get("direction", "")

        if direction == "BUY":
            # BUY : cloture M5 sous le milieu = retour dans le range
            if last_close < reference_mid:
                logger.debug(f"AntiChop BUY: cloture M5 {last_close:.5f} < MID {reference_mid:.5f} -> EXIT")
                return True
        elif direction == "SELL":
            # SELL : cloture M5 au-dessus du milieu = retour dans le range
            if last_close > reference_mid:
                logger.debug(f"AntiChop SELL: cloture M5 {last_close:.5f} > MID {reference_mid:.5f} -> EXIT")
                return True

        return False

    def _is_choppy_candles(self, candles: pd.DataFrame) -> bool:
        """Verifie si les bougies recentes sont en pattern de chop."""
        if len(candles) < 10:
            return False

        recent = candles.tail(10)
        bodies = abs(recent["close"] - recent["open"])
        ranges = recent["high"] - recent["low"]

        mean_body_ratio = (bodies / ranges).mean() if ranges.sum() > 0 else 0
        if mean_body_ratio > 0.6:
            return False

        directions = (recent["close"] > recent["open"]).astype(int)
        alternations = directions.diff().abs().sum()
        alternation_ratio = alternations / len(directions)

        return alternation_ratio > 0.5

    def _has_momentum(self, candles: pd.DataFrame) -> bool:
        """Verifie s'il y a du momentum directionnel."""
        if len(candles) < self._min_directional_candles:
            return False

        recent = candles.tail(self._min_directional_candles + 1)
        bullish = (recent["close"] > recent["open"]).sum()
        if bullish >= self._min_directional_candles:
            return True

        bearish = (recent["close"] < recent["open"]).sum()
        if bearish >= self._min_directional_candles:
            return True

        return False
