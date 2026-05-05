"""
phase_config.py — Configuration des phases de risque (P1/P2/Funded).

Définit les seuils de progression du challenge et les fractions de risque
associées à chaque phase.
"""

from config.settings import CHALLENGE_START_BALANCE

# ──────────────────────────────────────────────
# SEUILS DE PROGRESSION
# ──────────────────────────────────────────────
# P1     : balance < challenge_start * 1.08
# P2     : challenge_start * 1.08 <= balance < challenge_start * 1.08 * 1.05
# FUNDED : balance >= challenge_start * 1.08 * 1.05

P1_MULTIPLIER = 1.08
P2_MULTIPLIER = 1.08 * 1.05  # = 1.134

# ──────────────────────────────────────────────
# FRACTIONS DE RISQUE PAR PHASE
# ──────────────────────────────────────────────
PHASE_RISK_CONFIG = {
    "P1": {
        "risk_fraction": 0.50,
        "label": "Phase 1 — Challenge",
        "description": "Balance < 108% du capital de départ",
    },
    "P2": {
        "risk_fraction": 0.45,
        "label": "Phase 2 — Croissance",
        "description": "108% <= Balance < 113.4% du capital de départ",
    },
    "FUNDED": {
        "risk_fraction": 0.33,
        "label": "Funded — Compte financé",
        "description": "Balance >= 113.4% du capital de départ",
    },
}


def get_phase_thresholds() -> dict:
    """Retourne les seuils de passage d'une phase à l'autre.

    Returns:
        Dict avec les seuils P1 et P2 basés sur le capital de départ.
    """
    p1_threshold = CHALLENGE_START_BALANCE * P1_MULTIPLIER
    p2_threshold = CHALLENGE_START_BALANCE * P2_MULTIPLIER
    return {
        "P1_max": p1_threshold,
        "P2_max": p2_threshold,
        "FUNDED_min": p2_threshold,
    }
