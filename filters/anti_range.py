"""
anti_range.py — Anti-range pour le Forex.

Si le prix reste coince autour du bord de la boite asiatique pendant
plus de "anti_range_minutes" minutes sans direction claire -> annulation.

Condition : range des dernieres N minutes < 0.5 x ATR_M15
"""

from datetime import datetime, timedelta

from utils.time_utils import get_current_paris_time
from indicators.atr import calculate_atr
from utils.logger import get_logger

logger = get_logger("anti_range")


class AntiRange:
    """Bloque les trades pendant la periode de construction du range.

    Pour les actifs forex avec anti_range_minutes configure,
    bloque les trades pendant X minutes apres l'ouverture de session.
    """

    def __init__(self):
        self._range_periods = {}  # actif -> (heure_ouverture, minutes_blocage)

    def configure(self, asset_name: str, config: dict) -> None:
        """Configure la periode anti-range pour un actif.

        Args:
            asset_name: Nom standard de l'actif.
            config: Configuration de l'actif.
        """
        minutes = config.get("anti_range_minutes", 0)
        if minutes > 0:
            if config.get("contexte") == "asian_box":
                open_time = config.get("asian_box_start", "02:00")
            else:
                open_time = config.get("session_start", "00:00")

            self._range_periods[asset_name] = (open_time, minutes)
            logger.debug(
                f"AntiRange configure pour {asset_name}: "
                f"{open_time} + {minutes}min"
            )

    def is_in_range_period(self, asset_name: str) -> bool:
        """Verifie si on est dans la periode de construction du range."""
        if asset_name not in self._range_periods:
            return False

        open_time_str, block_minutes = self._range_periods[asset_name]
        now = get_current_paris_time()

        open_hour, open_min = map(int, open_time_str.split(":"))
        open_dt = now.replace(hour=open_hour, minute=open_min, second=0, microsecond=0)

        end_dt = open_dt + timedelta(minutes=block_minutes)

        return open_dt <= now <= end_dt

    def should_block_trade(self, asset_name: str) -> bool:
        """Blocage d'entree si dans la periode de range."""
        if self.is_in_range_period(asset_name):
            logger.warning(f"Trade bloque par anti-range pour {asset_name}")
            return True
        return False

    def check(self, asset: str, breakout_time: datetime,
              candles_m15: pd.DataFrame, atr_m15: float) -> bool:
        """Verifie si un signal actif doit etre annule par l'anti-range.

        Pour le Forex uniquement.
        Si le prix reste coince autour du bord de la box pendant
        plus de "anti_range_minutes" minutes sans direction claire -> annulation.

        Condition : range des dernieres N minutes < 0.5 x ATR_M15

        Args:
            asset: Nom standard de l'actif.
            breakout_time: Date/heure de la cassure.
            candles_m15: DataFrame M15.
            atr_m15: ATR M15.

        Returns:
            True si le signal doit etre annule (range confirme).
        """
        from config.market_config import MARKET_CONFIG
        config = MARKET_CONFIG.get(asset, {})
        range_minutes = config.get("anti_range_minutes", 45)
        if range_minutes <= 0:
            return False

        if candles_m15.empty or atr_m15 <= 0:
            return False

        # Verifier si assez de temps a passe depuis la cassure
        now = get_current_paris_time()
        if (now - breakout_time).total_seconds() < range_minutes * 60:
            return False

        # Calculer le range des dernieres N minutes
        if len(candles_m15) < range_minutes // 15:
            return False

        recent = candles_m15.tail(range_minutes // 15)
        range_recent = float(recent["high"].max() - recent["low"].min())

        # Si le range est trop petit par rapport a ATR => range confirme
        if range_recent < 0.5 * atr_m15:
            logger.info(f"AntiRange {asset}: range confirme ({range_recent:.5f} < 0.5*ATR), annulation")
            return True

        return False

    def get_remaining_minutes(self, asset_name: str) -> int:
        """Retourne les minutes restantes avant la fin du blocage."""
        if asset_name not in self._range_periods:
            return 0

        open_time_str, block_minutes = self._range_periods[asset_name]
        now = get_current_paris_time()

        open_hour, open_min = map(int, open_time_str.split(":"))
        open_dt = now.replace(hour=open_hour, minute=open_min, second=0, microsecond=0)

        end_dt = open_dt + timedelta(minutes=block_minutes)

        if now >= end_dt:
            return 0

        remaining = int((end_dt - now).total_seconds() / 60)
        return max(0, remaining)
