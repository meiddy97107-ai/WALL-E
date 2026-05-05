"""
risk_manager.py — Orchestrateur du systeme de gestion des risques.

Point d'entree unique pour toutes les decisions de risque.
Coordonne le detecteur de phase, le tracker de budget et le streak brake.
"""

from risk.phase_detector import PhaseDetector
from risk.budget_tracker import BudgetTracker
from risk.streak_brake import StreakBrake
from utils.logger import get_logger

logger = get_logger("risk_manager")


class RiskManager:
    """Orchestrateur du systeme de risque.

    Centralise les decisions de risque en combinant :
    - La phase detectee (P1/P2/Funded)
    - Le budget quotidien disponible
    - La protection anti-spirale (StreakBrake)
    """

    def __init__(self):
        self.phase_detector = PhaseDetector()
        self.budget_tracker = BudgetTracker()
        self.streak_brake = StreakBrake()
        self._current_phase = "P1"
        self._active_risk = {}  # ticket -> risk_eur

    # ──────────────────────────────────────────
    # INITIALISATION QUOTIDIENNE
    # ──────────────────────────────────────────

    def on_daily_reset(self, balance: float) -> dict:
        """Execute les operations de reset quotidien.

        Appele a 00h00 chaque jour :
        1. Met a jour la phase detectee
        2. Reset le budget quotidien
        3. Reset le streak brake

        Args:
            balance: Solde actuel du compte.

        Returns:
            Dict avec le resume du reset (phase, daily_budget).
        """
        self._current_phase = self.phase_detector.detect(balance)
        self.budget_tracker.reset_daily(balance)
        self.streak_brake.reset()
        self._active_risk.clear()

        risk_fraction = self.phase_detector.get_risk_fraction(balance)
        daily_budget = self.budget_tracker.get_daily_budget()

        logger.info(
            f"Reset quotidien — Phase: {self._current_phase}, "
            f"Budget: {daily_budget:.2f}, "
            f"Fraction risque: {risk_fraction:.2%}"
        )

        return {
            "phase": self._current_phase,
            "daily_budget": daily_budget,
            "risk_fraction": risk_fraction,
        }

    # ──────────────────────────────────────────
    # VERIFICATIONS AVANT TRADE
    # ──────────────────────────────────────────

    def is_trade_allowed(self, open_positions: list) -> bool:
        """Verifie toutes les conditions pour autoriser un nouveau trade.

        1. daily_budget disponible
        2. streak_brake.should_stop_trading() == False
        3. Le kill switch journalier n'est pas actif

        Args:
            open_positions: Liste des positions ouvertes.

        Returns:
            True si le trade peut etre ouvert.
        """
        # Budget disponible
        available = self.budget_tracker.get_available_budget(open_positions)
        if available <= 0:
            logger.warning(f"Budget quotidien epuise ({available:.2f}) — trade bloque.")
            return False

        # StreakBrake stop
        if self.streak_brake.should_stop_trading():
            logger.warning("StreakBrake: trading stoppe jusqu'a minuit.")
            return False

        # StreakBrake skip
        if self.streak_brake.should_skip_next_signal():
            logger.info("StreakBrake: skip prochain signal (2 pertes consecutives).")
            return False

        return True

    def can_trade(self, current_balance: float, open_positions: list) -> dict:
        """Ancienne interface — retourne dict avec can_trade et reason."""
        if self.budget_tracker.is_daily_limit_hit(current_balance):
            logger.warning("Daily loss limit atteinte — trading bloque.")
            return {"can_trade": False, "reason": "daily_limit_hit"}

        if self.streak_brake.should_stop_trading():
            logger.warning("StreakBrake kill switch active — trading bloque jusqu'a 00h00.")
            return {"can_trade": False, "reason": "streak_brake_kill"}

        if self.streak_brake.should_skip_next_signal():
            logger.info("StreakBrake: skip prochain signal apres 2 pertes consecutives.")
            return {"can_trade": False, "reason": "streak_brake_skip"}

        available = self.budget_tracker.get_available_budget(open_positions)
        if available <= 0:
            logger.warning(f"Budget quotidien epuise ({available:.2f}) — trading bloque.")
            return {"can_trade": False, "reason": "budget_exhausted"}

        return {"can_trade": True, "reason": "ok"}

    # ──────────────────────────────────────────
    # CALCUL DU RISQUE POUR UN TRADE
    # ──────────────────────────────────────────

    def calculate_risk_for_trade(self, current_balance: float) -> float:
        """Calcule le montant en euros a risquer sur le prochain trade.

        risk_eur = daily_budget x phase_fraction

        Phase P1     : x 0.50
        Phase P2     : x 0.45
        Phase FUNDED : x 0.33

        Args:
            current_balance: Solde actuel.

        Returns:
            Montant du risque en euros.
        """
        daily_budget = self.budget_tracker.get_daily_budget()
        risk_fraction = self.phase_detector.get_risk_fraction(current_balance)
        risk = daily_budget * risk_fraction
        logger.debug(f"Risque calcule pour le trade: {risk:.2f}")
        return risk

    def calculate_trade_risk(self, current_balance: float) -> float:
        """Alias pour compatibilite."""
        return self.calculate_risk_for_trade(current_balance)

    # ──────────────────────────────────────────
    # SUIVI DES TRADES
    # ──────────────────────────────────────────

    def on_trade_opened(self, ticket: int, risk_eur: float) -> None:
        """Notifie qu'une position SHIELD vient d'etre ouverte.

        Args:
            ticket: Ticket de la position.
            risk_eur: Montant risque en euros.
        """
        self._active_risk[ticket] = risk_eur
        logger.debug(f"Trade ouvert ticket={ticket} avec un risque de {risk_eur:.2f}")

    def on_trade_be_reached(self, ticket: int) -> None:
        """Notifie que la position est passee au BE -> exposition = 0.

        Args:
            ticket: Ticket de la position.
        """
        if ticket in self._active_risk:
            logger.debug(f"Trade ticket={ticket} au BE, risque libere.")
            del self._active_risk[ticket]

    def on_trade_closed(self, ticket: int, pnl_eur: float) -> None:
        """Notifie la cloture d'un trade.

        Calcule WIN ou LOSS et notifie le StreakBrake.

        Args:
            ticket: Ticket de la position.
            pnl_eur: Profit/Perte en euros.
        """
        if ticket in self._active_risk:
            del self._active_risk[ticket]

        result = "WIN" if pnl_eur >= 0 else "LOSS"
        self.streak_brake.on_trade_closed(result)
        logger.debug(f"Trade cloture ticket={ticket}: {result} (PnL={pnl_eur:+.2f})")

    # ──────────────────────────────────────────
    # ETAT DU RISK SYSTEM
    # ──────────────────────────────────────────

    def get_status(self) -> dict:
        """Retourne un resume complet de l'etat du risk system.

        Returns:
            Dict avec phase, daily_budget, exposure, available, pct_used, streak, balance.
        """
        daily_budget = self.budget_tracker.get_daily_budget()
        exposure = sum(self._active_risk.values())
        available = daily_budget - exposure
        pct_used = (exposure / daily_budget * 100) if daily_budget > 0 else 0
        streak_stats = self.streak_brake.get_stats()

        return {
            "phase": self._current_phase,
            "daily_budget": daily_budget,
            "exposure": exposure,
            "available": max(0, available),
            "pct_used": round(pct_used, 1),
            "streak": streak_stats.get("consecutive_losses", 0),
            "kill_switch": streak_stats.get("kill_switch", False),
        }

    # ──────────────────────────────────────────
    # ACCESSEURS
    # ──────────────────────────────────────────

    def get_current_phase(self) -> str:
        """Retourne la phase actuelle detectee."""
        return self._current_phase

    def get_daily_budget(self) -> float:
        """Retourne le budget quotidien."""
        return self.budget_tracker.get_daily_budget()

    def get_available_budget(self, open_positions: list) -> float:
        """Retourne le budget disponible."""
        return self.budget_tracker.get_available_budget(open_positions)
