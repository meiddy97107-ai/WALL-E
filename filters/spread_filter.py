"""
spread_filter.py — Filtre les spreads anormaux.

Compare le spread actuel a la moyenne historique (20 dernieres valeurs)
et bloque l'entree si le spread est anormal (> 2x la moyenne).
"""

from collections import deque

from utils.logger import get_logger

logger = get_logger("spread_filter")


class SpreadFilter:
    """Filtre les entrees basees sur le spread actuel.

    Maintient un historique dynamique du spread pour chaque actif
    et compare le spread actuel a la moyenne des 20 dernieres valeurs.
    """

    def __init__(self):
        # Historique des spreads par actif : {symbol: deque(maxlen=20)}
        self._spread_history = {}

    def update(self, asset: str, current_spread: float) -> None:
        """Met a jour l'historique du spread pour un actif.

        Args:
            asset: Nom standard de l'actif.
            current_spread: Spread actuel.
        """
        if asset not in self._spread_history:
            self._spread_history[asset] = deque(maxlen=20)
        self._spread_history[asset].append(current_spread)

    def is_blocked(self, asset: str, current_spread: float) -> bool:
        """Verifie si le spread est anormal -> pas d'entree.

        Spread anormal = spread_actuel > 2.0 x spread_moyen (20 dernieres valeurs).

        Args:
            asset: Nom standard de l'actif.
            current_spread: Spread actuel.

        Returns:
            True si le spread est anormal.
        """
        history = self._spread_history.get(asset)
        if history is None or len(history) < 5:
            return False  # Pas assez de donnees

        # Mettre a jour avec la valeur actuelle
        self.update(asset, current_spread)

        mean_spread = sum(history) / len(history)
        if mean_spread <= 0:
            return False

        is_abnormal = current_spread > 2.0 * mean_spread

        if is_abnormal:
            logger.warning(
                f"Spread anormal pour {asset}: "
                f"{current_spread:.5f} (moyenne: {mean_spread:.5f}, "
                f"max: {2.0 * mean_spread:.5f})"
            )

        return is_abnormal

    def should_block_trade(self, current_spread: float, symbol: str) -> bool:
        """Ancienne interface : bloque si spread anormal."""
        return self.is_blocked(symbol, current_spread)

    def get_spread_history(self, asset: str) -> list:
        """Retourne l'historique des spreads pour un actif."""
        return list(self._spread_history.get(asset, []))
