"""
phase_detector.py — Détection automatique de la phase du challenge.

Détermine dans quelle phase (P1, P2, FUNDED) se trouve le compte
en fonction du solde actuel et du capital de départ.
"""

from config.settings import CHALLENGE_START_BALANCE
from config.phase_config import PHASE_RISK_CONFIG, P1_MULTIPLIER, P2_MULTIPLIER
from utils.logger import get_logger

logger = get_logger("phase_detector")


class PhaseDetector:
    """Détecte automatiquement dans quelle phase du challenge se trouve le compte.

    Les seuils sont définis dans phase_config.py :
    P1     : balance < challenge_start * 1.08
    P2     : challenge_start * 1.08 <= balance < challenge_start * 1.08 * 1.05
    FUNDED : balance >= challenge_start * 1.08 * 1.05
    """

    def __init__(self):
        self._start_balance = CHALLENGE_START_BALANCE

    def detect(self, current_balance: float) -> str:
        """Détecte la phase actuelle en fonction du solde.

        Args:
            current_balance: Solde actuel du compte.

        Returns:
            "P1", "P2" ou "FUNDED".
        """
        if self._start_balance <= 0:
            logger.warning("CHALLENGE_START_BALANCE non défini dans .env — phase par défaut: P1")
            return "P1"

        p1_max = self._start_balance * P1_MULTIPLIER
        p2_max = self._start_balance * P2_MULTIPLIER  # FUNDED min

        if current_balance < p1_max:
            return "P1"
        elif current_balance < p2_max:
            return "P2"
        else:
            return "FUNDED"

    def get_risk_fraction(self, current_balance: float) -> float:
        """Retourne la fraction de risque selon la phase.

        Args:
            current_balance: Solde actuel.

        Returns:
            Fraction de risque (0.50 pour P1, 0.45 pour P2, 0.33 pour FUNDED).
        """
        phase = self.detect(current_balance)
        return PHASE_RISK_CONFIG[phase]["risk_fraction"]

    def get_phase_label(self, current_balance: float) -> str:
        """Retourne le libellé complet de la phase.

        Args:
            current_balance: Solde actuel.

        Returns:
            Libellé de la phase (ex: "Phase 1 — Challenge").
        """
        phase = self.detect(current_balance)
        return PHASE_RISK_CONFIG[phase]["label"]

    def get_phase_description(self, current_balance: float) -> str:
        """Retourne la description complète de la phase.

        Args:
            current_balance: Solde actuel.

        Returns:
            Description textuelle de la phase.
        """
        phase = self.detect(current_balance)
        return PHASE_RISK_CONFIG[phase]["description"]

    def is_in_phase(self, current_balance: float, target_phase: str) -> bool:
        """Vérifie si le compte est dans une phase spécifique.

        Args:
            current_balance: Solde actuel.
            target_phase: Phase cible ("P1", "P2", ou "FUNDED").

        Returns:
            True si le compte est dans la phase cible.
        """
        return self.detect(current_balance) == target_phase
