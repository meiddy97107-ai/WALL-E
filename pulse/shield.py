"""
shield.py — État 1 du PULSE : protection du capital.

Stop fixe initial. La position reste en SHIELD jusqu'à ce que
le profit atteigne le seuil de passage en TRACKER.

Transition vers TRACKER quand :
profit >= be_threshold × ATR_M1
(be_threshold × 0.80 si conviction == "HIGH")

Au passage TRACKER : stop ramené au prix d'entrée (break-even).
"""

from utils.logger import get_logger

logger = get_logger("pulse_shield")


class Shield:
    """État 1 : stop fixe, protection du capital.

    Surveille le profit de la position et déclenche la transition
    vers TRACKER lorsque le seuil de break-even est atteint.
    """

    def __init__(self, data_feed=None):
        self.data_feed = data_feed

    def update(self, position: dict, atr_m1: float, config: dict) -> dict:
        """Met à jour une position en état SHIELD.

        Vérifie si le profit atteint le seuil de transition vers TRACKER.
        Si oui, ramène le stop au prix d'entrée (break-even) et change l'état.

        Args:
            position: Dict de la position avec prix_entree, direction, conviction.
            atr_m1: ATR sur timeframe M1.
            config: Configuration de l'actif (contient be_threshold).

        Returns:
            Dict de la position mise à jour (avec nouvel état si transition).
        """
        updated = dict(position)

        if atr_m1 <= 0:
            return updated

        # Récupérer le seuil de break-even depuis la config
        be_threshold = config.get("be_threshold", 1.0)

        # Réduction du seuil pour les trades à haute conviction
        if position.get("conviction") == "HIGH":
            be_threshold *= 0.80

        # Seuil de profit pour passer en TRACKER
        target_profit = be_threshold * atr_m1

        # Calculer le profit actuel en points de prix
        current_price = self._get_current_price(position)
        if current_price == 0.0:
            return updated

        if position["direction"] == "BUY":
            profit_points = current_price - position["prix_entree"]
        else:
            profit_points = position["prix_entree"] - current_price

        # Transition vers TRACKER si le seuil est atteint
        if profit_points >= target_profit:
            updated["etat"] = "TRACKER"
            updated["sl"] = position["prix_entree"]  # Break-even
            conviction = position.get("conviction", "STANDARD")
            be_notice = f" (Conviction: {conviction}, BE x0.80)" if conviction == "HIGH" else ""
            logger.info(
                f"SHIELD -> TRACKER: ticket={position['ticket']}, "
                f"profit={profit_points:.5f} >= target={target_profit:.5f}, "
                f"SL ramene au BE ({position['prix_entree']:.5f}){be_notice}"
            )

        return updated

    def _get_current_price(self, position: dict) -> float:
        """Estime le prix actuel depuis les données disponibles.

        Pour l'instant, retourne le prix d'entrée pour éviter
        les appels MT5 depuis le PULSE. La vraie implémentation
        viendra avec l'intégration DataFeed.

        Returns:
            Prix estimé actuel.
        """
        if self.data_feed is not None:
            asset = position.get("actif")
            if asset:
                px = self.data_feed.get_current_price(asset)
                if isinstance(px, dict):
                    if position.get("direction") == "BUY":
                        return float(px.get("bid", 0.0))
                    return float(px.get("ask", 0.0))
        return position.get("prix_entree", 0.0)
