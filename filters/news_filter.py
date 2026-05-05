"""
news_filter.py — Filtre les periodes de news / volatilite anormale.

Pour les indices : verifie si l'ATR M1 a double pendant la fenetre ORB.
Pour le Forex    : pause 30 min avant/apres une annonce majeure.

La liste des annonces doit etre fournie manuellement
ou via une API de calendrier economique.
"""

from datetime import datetime, timedelta

from utils.logger import get_logger

logger = get_logger("news_filter")

BLOCK_BEFORE_NEWS = 30  # minutes
BLOCK_AFTER_NEWS = 30   # minutes


class NewsFilter:
    """Filtre les signaux de trading pendant les periodes de news."""

    def __init__(self):
        self.news_times = []  # Liste de datetime UTC des annonces
        self._major_news = [
            ("08:30", "US NFP"),
            ("08:30", "US CPI"),
            ("08:30", "US GDP"),
            ("08:30", "US Retail Sales"),
            ("10:00", "US ISM Manufacturing"),
            ("10:00", "US ISM Services"),
            ("14:00", "FOMC Statement"),
            ("14:30", "FOMC Press Conference"),
        ]

    def add_news(self, news_datetime: datetime) -> None:
        """Ajoute une annonce manuellement.

        Args:
            news_datetime: Date/heure UTC de l'annonce.
        """
        self.news_times.append(news_datetime)
        logger.debug(f"News ajoutee: {news_datetime} UTC")

    def add_news_event(self, time_str: str, title: str) -> None:
        """Ajoute un evenement news par heure.

        Args:
            time_str: Heure UTC au format "HH:MM".
            title: Titre de l'evenement.
        """
        self._major_news.append((time_str, title))
        logger.debug(f"News ajoutee: {title} a {time_str} UTC")

    def is_blocked(self, asset: str, atr_current: float = None,
                   atr_reference: float = None) -> bool:
        """Verifie si le trading est bloque par les news.

        Args:
            asset: Nom standard de l'actif.
            atr_current: ATR actuel (pour les indices).
            atr_reference: ATR de reference (pour les indices).

        Returns:
            True si le trading est bloque.
        """
        # Pour les indices : verifier si l'ATR a double
        if atr_current is not None and atr_reference is not None:
            if atr_reference > 0 and atr_current > 2.0 * atr_reference:
                logger.warning(f"NewsFilter {asset}: ATR double ({atr_current:.2f} vs {atr_reference:.2f})")
                return True

        # Pour le Forex : verifier les annonces
        if self._is_near_news_period():
            logger.warning(f"NewsFilter {asset}: proximite d'annonce economique")
            return True

        return False

    def is_volatile(self, atr_current: float, atr_reference: float) -> bool:
        """Verifie si l'ATR a double -> journee annulee pour les indices.

        Args:
            atr_current: ATR actuel.
            atr_reference: ATR de reference (moyenne journaliere).

        Returns:
            True si volatilite anormale.
        """
        if atr_reference <= 0:
            return False
        return atr_current > 2.0 * atr_reference

    def is_news_period(self) -> bool:
        """Verifie si on est dans une fenetre de news."""
        now = datetime.utcnow()
        now_minutes = now.hour * 60 + now.minute

        for news_time_str, _ in self._major_news:
            hours, minutes = map(int, news_time_str.split(":"))
            news_minutes = hours * 60 + minutes

            start_block = news_minutes - BLOCK_BEFORE_NEWS
            end_block = news_minutes + BLOCK_AFTER_NEWS

            if start_block <= now_minutes <= end_block:
                return True
        return False

    def _is_near_news_period(self) -> bool:
        """Verifie la proximite avec les annonces programmees."""
        now = datetime.utcnow()
        now_minutes = now.hour * 60 + now.minute

        for news_time_str, _ in self._major_news:
            hours, minutes = map(int, news_time_str.split(":"))
            news_minutes = hours * 60 + minutes

            start_block = news_minutes - BLOCK_BEFORE_NEWS
            end_block = news_minutes + BLOCK_AFTER_NEWS

            if start_block <= now_minutes <= end_block:
                logger.info(f"News period detectee: {news_time_str} UTC")
                return True

        # Verifier les annonces ajoutees manuellement
        for news_dt in self.news_times:
            diff = (now - news_dt).total_seconds() / 60
            if -BLOCK_BEFORE_NEWS <= diff <= BLOCK_AFTER_NEWS:
                return True

        return False

    def should_block_trade(self) -> bool:
        """Ancienne interface : bloque si periode de news."""
        return self.is_news_period()

    def get_upcoming_news(self) -> list:
        """Retourne les prochaines news dans les 2 heures."""
        now = datetime.utcnow()
        now_minutes = now.hour * 60 + now.minute
        upcoming = []

        for news_time_str, title in self._major_news:
            hours, minutes = map(int, news_time_str.split(":"))
            news_minutes = hours * 60 + minutes

            if now_minutes <= news_minutes <= now_minutes + 120:
                upcoming.append((news_time_str, title))

        return upcoming
