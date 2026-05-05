"""
budget_tracker.py — Suivi du budget quotidien et de l'exposition en temps réel.

Gère :
- Le snapshot du solde à 00h00
- Le calcul du daily budget (4% du snapshot)
- L'exposition réelle (seules les positions en état SHIELD comptent)
- La vérification de la limite de perte quotidienne
"""

from config.settings import DAILY_RISK_PERCENT
from utils.logger import get_logger

logger = get_logger("budget_tracker")


class BudgetTracker:
    """Gère le daily budget et l'exposition réelle en temps réel.

    Règles d'exposition :
    - Position en état SHIELD  → compte pour risk_initial_€
    - Position en état TRACKER → compte pour 0€ (slot libéré)
    - Position en état ROCKET  → compte pour 0€ (slot libéré)
    """

    def __init__(self):
        self._snapshot_balance = 0.0
        self._daily_budget = 0.0

    def reset_daily(self, balance: float) -> None:
        """Réinitialise le budget quotidien avec un snapshot du solde.

        Appelé à 00h00 chaque jour. Calcule le daily budget = 4% du solde.

        Args:
            balance: Solde actuel du compte (snapshot).
        """
        self._snapshot_balance = balance
        self._daily_budget = balance * (DAILY_RISK_PERCENT / 100.0)
        logger.info(
            f"Budget quotidien réinitialisé — "
            f"Snapshot: {balance:.2f}€, Budget: {self._daily_budget:.2f}€"
        )

    def get_daily_budget(self) -> float:
        """Retourne le budget quotidien.

        Returns:
            Budget quotidien en euros.
        """
        return self._daily_budget

    def get_real_exposure(self, open_positions: list) -> float:
        """Calcule l'exposition réelle en additionnant les risques SHIELD.

        Seules les positions en état SHIELD comptent dans l'exposition.
        Les positions en TRACKER ou ROCKET ont leur risque libéré.

        Args:
            open_positions: Liste des positions ouvertes, chaque position
                          doit contenir une clé "etat" et "risk_initial_€".

        Returns:
            Exposition réelle totale en euros.
        """
        exposure = 0.0
        for pos in open_positions:
            if pos.get("etat") == "SHIELD":
                exposure += pos.get("risk_initial_", 0.0)
        return exposure

    def get_available_budget(self, open_positions: list) -> float:
        """Calcule le budget disponible = daily_budget - exposition réelle.

        Args:
            open_positions: Liste des positions ouvertes avec état et risque.

        Returns:
            Budget disponible en euros.
        """
        return self._daily_budget - self.get_real_exposure(open_positions)

    def is_daily_limit_hit(self, current_balance: float) -> bool:
        """Vérifie si la limite de perte quotidienne est atteinte.

        La limite est atteinte quand la perte du jour (snapshot - balance)
        dépasse ou égale le daily budget.

        Args:
            current_balance: Solde actuel.

        Returns:
            True si la limite de perte quotidienne est atteinte.
        """
        if self._snapshot_balance <= 0:
            return False
        loss = self._snapshot_balance - current_balance
        return loss >= self._daily_budget

    def calculate_risk_for_trade(self, current_balance: float, risk_fraction: float = 0.50) -> float:
        """Calcule le montant à risquer sur le prochain trade.

        Risk = daily_budget * risk_fraction (selon la phase).

        Args:
            current_balance: Solde actuel (pour recalcul si nécessaire).
            risk_fraction: Fraction du budget à risquer (0.50 par défaut).

        Returns:
            Montant du risque en euros.
        """
        return self._daily_budget * risk_fraction

    def get_snapshot_balance(self) -> float:
        """Retourne le solde snapshot du début de journée."""
        return self._snapshot_balance
