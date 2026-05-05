"""
pulse_manager.py — Orchestrateur PULSE finalise.

Maintient l'etat de chaque position ouverte.
Appelle Shield, Tracker ou Rocket selon l'etat de chaque position.
Applique les transitions, modifie les SL, gere les anti-chop.
"""

from pulse.shield import Shield
from pulse.tracker import Tracker
from pulse.rocket import Rocket
from core.data_feed import DataFeed
from core.order_manager import OrderManager
from risk.risk_manager import RiskManager
from config.market_config import MARKET_CONFIG
from filters.anti_chop import AntiChop
from utils.logger import get_logger

logger = get_logger("pulse_manager")

POSITION_TEMPLATE = {
    "ticket": 0,
    "actif": "",
    "direction": "",
    "prix_entree": 0.0,
    "sl": 0.0,
    "risk_initial_": 0.0,
    "etat": "SHIELD",
    "action": "CONTINUE",
    "compteur_rocket": 0,
    "conviction": "STANDARD",
    "strategie": "",
    "reference_mid": 0.0,
}


class PulseManager:
    """Orchestrateur du systeme PULSE.

    Maintient l'etat de chaque position ouverte et orchestre
    Shield -> Tracker -> Rocket avec transitions automatiques.
    """

    def __init__(self, data_feed: DataFeed, order_manager: OrderManager,
                 risk_manager: RiskManager):
        self.data_feed = data_feed
        self.order_mgr = order_manager
        self.risk_mgr = risk_manager
        self._positions = {}

        self.shield = Shield(data_feed)
        self.tracker = Tracker()
        self.rocket = Rocket(data_feed)
        self.anti_chop = AntiChop()

    # ──────────────────────────────────────────
    # MISE A JOURNAL (appele a chaque bougie M1)
    # ──────────────────────────────────────────

    def update_all(self, open_positions: list) -> None:
        """Met a jour toutes les positions actives.

        Appele a chaque bougie M1 pour chaque position ouverte.
        """
        self._sync_positions(open_positions)

        if not self._positions:
            return

        for ticket, position in list(self._positions.items()):
            try:
                self._update_position(ticket, position)
            except Exception as e:
                logger.error(f"Erreur PULSE update pour ticket={ticket}: {e}")

    def _update_position(self, ticket: int, position: dict) -> None:
        """Execute une mise a jour complete sur une position.

        1. Recuperer les donnees (M1, M5, ATR)
        2. Recuperer la config de l'actif
        3. Verifier l'anti-chop sur M5
        4. Appeler l'etat actuel (Shield/Tracker/Rocket)
        5. Gerer les transitions (SL, BE, etc.)
        6. Logger les changements
        """
        asset = position["actif"]
        config = MARKET_CONFIG.get(asset, {})

        candles_m1 = self.data_feed.get_candles(asset, "M1", 50)
        candles_m5 = self.data_feed.get_candles(asset, "M5", 20)

        if candles_m1.empty:
            return

        from indicators.atr import calculate_atr
        atr_m1 = calculate_atr(candles_m1, 14)

        old_etat = position["etat"]

        # Appliquer l'etat actuel
        if position["etat"] == "SHIELD":
            updated = self.shield.update(position, atr_m1, config)
        elif position["etat"] == "TRACKER":
            updated = self.tracker.update(position, atr_m1, candles_m1, config)
        elif position["etat"] == "ROCKET":
            updated = self.rocket.update(position, atr_m1, candles_m1, config)
        else:
            return

        # Gerer la transition SHIELD -> TRACKER (modifier SL au BE)
        if updated["etat"] == "TRACKER" and old_etat == "SHIELD":
            price = position.get("prix_entree", 0)
            if price > 0:
                self.order_mgr.modify_sl(ticket, price)
                self.risk_mgr.on_trade_be_reached(ticket)
                logger.info(f"PULSE: SL ramene au BE pour ticket={ticket}")

        # Appliquer le nouveau SL de TRACKER/ROCKET si ameliore
        new_sl = updated.get("sl", position.get("sl"))
        old_sl = position.get("sl")
        if new_sl is not None and old_sl is not None and new_sl != old_sl:
            if self.order_mgr.modify_sl(ticket, float(new_sl)):
                logger.debug(f"PULSE: SL ajuste ticket={ticket} {old_sl:.5f} -> {float(new_sl):.5f}")

        # Gerer les EXIT
        if updated.get("action") == "EXIT" or updated.get("etat") == "EXIT":
            logger.info(f"PULSE EXIT: fermeture ticket={ticket} raison={updated.get('etat', 'EXIT')}")
            self.order_mgr.close_position(ticket, reason=f"PULSE_{old_etat}")
            self._positions.pop(ticket, None)
            self.rocket.release_asset(asset)
            return

        # Anti-chop (apres TRACKER/ROCKET)
        if updated["etat"] in ["TRACKER", "ROCKET"]:
            reference_mid = position.get("reference_mid", 0)
            if reference_mid > 0 and not candles_m5.empty:
                if self.anti_chop.check(position, reference_mid, candles_m5):
                    logger.info(f"PULSE AntiChop: fermeture ticket={ticket}")
                    self.order_mgr.close_position(ticket, reason="ANTI_CHOP")
                    self._positions.pop(ticket, None)
                    self.rocket.release_asset(asset)
                    return

        # Mettre a jour la position
        self._positions[ticket] = updated
        if hasattr(self.order_mgr, "sync_state"):
            self.order_mgr.sync_state(ticket, updated)

        # Logger les transitions
        if updated["etat"] != old_etat:
            logger.info(f"PULSE transition: ticket={ticket} {old_etat} -> {updated['etat']}")

    # ──────────────────────────────────────────
    # GESTION DES POSITIONS
    # ──────────────────────────────────────────

    def on_position_opened(self, position_info: dict) -> None:
        """Enregistre une nouvelle position dans le PULSE.

        position_info doit contenir :
        {
            "ticket": int,
            "actif": str,
            "direction": str,
            "prix_entree": float,
            "sl": float,
            "risk_initial_": float,
            "etat": "SHIELD",
            "conviction": str,
            "strategie": str,
            "reference_mid": float,
        }
        """
        ticket = position_info.get("ticket", 0)
        if ticket == 0:
            logger.error("Tentative d'enregistrement d'une position sans ticket valide.")
            return

        new_position = POSITION_TEMPLATE.copy()
        new_position.update({
            "ticket": ticket,
            "actif": position_info.get("actif", position_info.get("symbol", "")),
            "direction": position_info.get("direction", ""),
            "prix_entree": position_info.get("prix_entree", position_info.get("price", 0.0)),
            "sl": position_info.get("sl", 0.0),
            "risk_initial_": position_info.get("risk_initial_", 0.0),
            "conviction": position_info.get("conviction", "STANDARD"),
            "strategie": position_info.get("strategie", position_info.get("scenario", "")),
            "reference_mid": position_info.get("reference_mid", 0.0),
        })

        self._positions[ticket] = new_position
        logger.info(
            f"Position enregistree dans PULSE: ticket={ticket}, "
            f"{new_position['direction']} {new_position['actif']}, "
            f"SL={new_position['sl']:.5f}, conviction={new_position['conviction']}"
        )

    def on_position_closed(self, ticket: int, reason: str = "") -> None:
        """Supprime une position du PULSE apres cloture.

        Notifie le RiskManager (WIN ou LOSS selon le PnL).

        Args:
            ticket: Ticket de la position.
            reason: Raison de la cloture.
        """
        if ticket in self._positions:
            position = self._positions.pop(ticket)
            logger.info(
                f"Position retiree du PULSE: ticket={ticket}, "
                f"etat={position['etat']}, strategie={position['strategie']}"
            )
            self.rocket.release_asset(position["actif"])
        else:
            logger.debug(f"Position ticket={ticket} non trouvee dans le PULSE.")

    # ──────────────────────────────────────────
    # ACCESSEURS
    # ──────────────────────────────────────────

    def has_rocket_active(self, asset: str) -> bool:
        """True si une position ROCKET est active sur cet actif."""
        return self.rocket.is_asset_locked(asset)

    def has_open_position(self, asset: str, strategie: str = None) -> bool:
        """True si une position est ouverte sur cet actif.

        Args:
            asset: Nom de l'actif.
            strategie: Filtre optionnel par strategie.

        Returns:
            True si une position correspondante existe.
        """
        for pos in self._positions.values():
            if pos["actif"] == asset:
                if strategie is None or pos.get("strategie") == strategie:
                    return True
        return False

    def get_exposure_by_state(self) -> dict:
        """Retourne le detail de l'exposition par etat PULSE.

        Returns:
            Dict avec SHIELD, TRACKER, ROCKET, total.
        """
        result = {"SHIELD": 0.0, "TRACKER": 0.0, "ROCKET": 0.0, "total": 0.0}
        for pos in self._positions.values():
            etat = pos.get("etat", "SHIELD")
            risk = pos.get("risk_initial_", 0)
            if etat == "SHIELD":
                result["SHIELD"] += risk
                result["total"] += risk
            elif etat == "TRACKER":
                result["TRACKER"] += 0  # Au BE, exposition = 0
            elif etat == "ROCKET":
                result["ROCKET"] += 0  # Au BE ou au-dela, exposition = 0
        return result

    def get_position_state(self, ticket: int) -> dict:
        """Retourne l'etat PULSE d'une position."""
        return self._positions.get(ticket, {})

    def get_all_positions(self) -> list:
        """Retourne toutes les positions gerees par le PULSE."""
        return list(self._positions.values())

    def clear_all(self) -> None:
        """Vide toutes les positions (appele par kill switch)."""
        self._positions.clear()
        logger.warning("PULSE: toutes les positions videes (kill switch).")

    # ──────────────────────────────────────────
    # SYNCHRONISATION
    # ──────────────────────────────────────────

    def _sync_positions(self, open_positions: list) -> None:
        """Synchronise les positions PulseManager avec MT5.

        Retire les positions qui n'existent plus dans MT5.
        """
        active_tickets = {p["ticket"] for p in open_positions}
        for ticket in list(self._positions.keys()):
            if ticket not in active_tickets:
                self.on_position_closed(ticket, reason="MT5_SYNC")
