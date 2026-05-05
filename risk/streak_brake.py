"""
streak_brake.py — Protection anti-spirale de pertes.

Système de sécurité qui réduit automatiquement l'activité en cas
de pertes consécutives pour éviter les comportements de revenge trading.

Règles :
- 2 pertes consécutives → ignorer le prochain signal
- 3 pertes consécutives → kill switch jusqu'à 00h00
"""

from utils.logger import get_logger

logger = get_logger("streak_brake")


class StreakBrake:
    """Protection anti-spirale basée sur les pertes consécutives.

    Maintient un compteur de pertes consécutives et applique
    des pénalités progressives.
    """

    def __init__(self):
        self._consecutive_losses = 0
        self._consecutive_wins = 0
        self._total_trades = 0
        self._kill_switch = False

    def on_trade_closed(self, result: str) -> None:
        """Met à jour l'état après la clôture d'un trade.

        Args:
            result: "WIN" ou "LOSS".
        """
        self._total_trades += 1

        if result.upper() == "LOSS":
            self._consecutive_losses += 1
            self._consecutive_wins = 0

            if self._consecutive_losses >= 3:
                self._kill_switch = True
                logger.warning(
                    f"StreakBrake: {self._consecutive_losses} pertes consécutives — "
                    f"KILL SWITCH activé jusqu'à 00h00."
                )
            elif self._consecutive_losses == 2:
                logger.info(
                    f"StreakBrake: {self._consecutive_losses} pertes consécutives — "
                    f"prochain signal ignoré."
                )
            else:
                logger.debug(f"StreakBrake: {self._consecutive_losses} perte consécutive.")

        elif result.upper() == "WIN":
            self._consecutive_wins += 1
            self._consecutive_losses = 0

            if self._consecutive_wins >= 3:
                logger.debug(f"StreakBrake: {self._consecutive_wins} victoires consécutives.")
        else:
            logger.warning(f"StreakBrake: résultat inconnu '{result}' ignoré.")

    def should_skip_next_signal(self) -> bool:
        """Vérifie si le prochain signal doit être ignoré.

        2 pertes consécutives → skip le prochain signal.

        Returns:
            True si le prochain signal doit être ignoré.
        """
        return self._consecutive_losses == 2 and not self._kill_switch

    def should_stop_trading(self) -> bool:
        """Vérifie si le trading doit être complètement arrêté.

        3+ pertes consécutives → kill switch.

        Returns:
            True si le trading doit être arrêté.
        """
        return self._kill_switch

    def reset(self) -> None:
        """Réinitialise tous les compteurs.

        Appelé à 00h00 chaque jour.
        """
        self._consecutive_losses = 0
        self._consecutive_wins = 0
        self._kill_switch = False
        logger.info("StreakBrake réinitialisé (nouveau jour).")

    def get_stats(self) -> dict:
        """Retourne les statistiques actuelles du StreakBrake.

        Returns:
            Dict avec les compteurs actuels.
        """
        return {
            "consecutive_losses": self._consecutive_losses,
            "consecutive_wins": self._consecutive_wins,
            "total_trades": self._total_trades,
            "kill_switch": self._kill_switch,
        }
