"""
main.py — ORB STRUCTURE PRO v2.0 — Boucle principale complete.

Sequence de demarrage :
1. Charger la config (.env + market_config)
2. Logger le demarrage avec phase detectee et solde
3. Connecter MT5 (auto-launch si necessaire)
4. Verifier que tous les symboles sont disponibles
5. Initialiser tous les modules
6. Lancer la boucle principale

Ordre d'execution strict du cycle :
Reset -> Kill switch -> Daily limit -> Streak -> PULSE -> SMC -> STRUCTURE TRAP
"""

import time
import sys
import signal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import MODE, CHALLENGE_START_BALANCE, MAGIC_NUMBER
from config.market_config import MARKET_CONFIG, get_symbol
from core.mt5_connector import MT5Connector
from core.data_feed import DataFeed
from core.order_manager import OrderManager
from risk.risk_manager import RiskManager
from pulse.pulse_manager import PulseManager
from pulse.rocket import Rocket
from strategies.smc_session import SMCSession
from strategies.structure_trap import StructureTrap
from filters.news_filter import NewsFilter
from filters.spread_filter import SpreadFilter
from filters.anti_chop import AntiChop
from filters.anti_range import AntiRange
from utils.logger import get_logger
from utils.time_utils import (
    is_time,
    is_time_between,
    get_current_paris_time,
    seconds_until_next_m1,
)
from utils.calculator import points_to_price

logger = get_logger("main")

SMC_ASSETS = ["EURUSD", "GBPUSD", "XAUUSD"]


class BotOrbStructurePro:
    """Bot de trading algorithmique ORB STRUCTURE PRO v2.0."""

    def __init__(self):
        self.running = False
        self.mt5 = None
        self.data_feed = None
        self.order_manager = None
        self.risk_manager = None
        self.pulse_manager = None
        self.smc_session = None
        self.structure_trap = None
        self.news_filter = None
        self.spread_filter = None
        self.anti_chop = None
        self.anti_range = None

    # ──────────────────────────────────────────
    # INITIALISATION
    # ──────────────────────────────────────────

    def initialize(self) -> bool:
        """Initialise tous les composants du bot.

        Returns:
            True si l'initialisation a reussi.
        """
        logger.info("=" * 60)
        logger.info("ORB STRUCTURE PRO v2.0 — Demarrage")
        logger.info(f"Mode: {MODE} | Magic: {MAGIC_NUMBER}")
        logger.info("=" * 60)

        if CHALLENGE_START_BALANCE <= 0:
            logger.error("CHALLENGE_START_BALANCE non defini dans le .env.")
            return False

        # Modules sans MT5
        self.news_filter = NewsFilter()
        self.spread_filter = SpreadFilter()
        self.anti_chop = AntiChop()
        self.anti_range = AntiRange()

        for asset_name, config in MARKET_CONFIG.items():
            self.anti_range.configure(asset_name, config)

        # Modules MT5
        self.mt5 = MT5Connector()
        self.data_feed = DataFeed()

        if MODE != "PAPER":
            if not self.mt5.connect():
                logger.error("Impossible de se connecter a MT5. Arret.")
                return False
            self._verify_symbols()

        self.order_manager = OrderManager()
        self.risk_manager = RiskManager()
        self.pulse_manager = PulseManager(self.data_feed, self.order_manager,
                                          self.risk_manager)
        self.smc_session = SMCSession(self.data_feed)
        self.structure_trap = StructureTrap(self.data_feed)

        # Log de demarrage
        balance = self._get_balance()
        phase = self.risk_manager.phase_detector.detect(balance)
        logger.info(f"=== BOT DEMARRE | Solde: {balance:.2f} | Phase: {phase} ===")

        return True

    # ──────────────────────────────────────────
    # BOUCLE PRINCIPALE
    # ──────────────────────────────────────────

    def run(self) -> None:
        """Lance la boucle principale du bot."""
        if not self.initialize():
            return

        self.running = True
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info("Boucle principale demarree.")

        while self.running:
            try:
                self._run_cycle()
                time.sleep(seconds_until_next_m1())
            except Exception as e:
                logger.error(f"Erreur dans la boucle principale: {e}")
                if MODE != "PAPER" and not self.mt5.is_connected():
                    logger.warning("Connexion perdue — tentative de reconnexion...")
                    self.mt5.reconnect()
                time.sleep(5)

        self._shutdown()

    def _run_cycle(self) -> None:
        """Un cycle complet execute a chaque bougie M1.

        L'ordre d'execution est STRICT et ne doit jamais etre modifie.
        """
        balance = self._get_balance()
        now = get_current_paris_time()

        # ── ETAPE 1 — RESET QUOTIDIEN (00h00) ────────────────────────
        if is_time("00:00"):
            self.risk_manager.on_daily_reset(balance)
            self.smc_session.reset_daily()
            phase = self.risk_manager.get_current_phase()
            budget = self.risk_manager.get_daily_budget()
            logger.info(f"=== RESET QUOTIDIEN | Solde: {balance:.2f} | "
                        f"Budget: {budget:.2f} | Phase: {phase} ===")

        # ── ETAPE 2 — KILL SWITCH HORAIRE (21h45) ────────────────────
        if is_time_between("21:45", "23:59"):
            logger.info("Kill switch horaire 21h45 — plus de nouveaux trades.")
            # On ne ferme pas les trades existants, on bloque juste les nouveaux
            return

        # ── ETAPE 3 — VERIFICATION CONNEXION MT5 ────────────────────
        if MODE != "PAPER" and not self.mt5.is_connected():
            logger.warning("Connexion MT5 perdue. Tentative de reconnexion...")
            if not self.mt5.reconnect():
                return

        # ── ETAPE 4 — VERIFICATION DAILY LOSS LIMIT ──────────────────
        if self.risk_manager.budget_tracker.is_daily_limit_hit(balance):
            logger.warning("Daily loss limit atteinte (4%). Arret des nouveaux trades.")
            return

        # ── ETAPE 5 — STREAK BRAKE ───────────────────────────────────
        skip_next = self.risk_manager.streak_brake.should_skip_next_signal()
        if self.risk_manager.streak_brake.should_stop_trading():
            logger.warning("STREAK BRAKE: trading stoppe jusqu'a minuit.")
            return

        # ── ETAPE 6 — PULSE : GESTION DES POSITIONS OUVERTES ────────
        open_positions = self.order_manager.get_open_positions()
        self.pulse_manager.update_all(open_positions)

        # ── ETAPE 7 — SMC SESSION : DIRECTION LONDON (10h00) ────────
        if is_time("10:00"):
            for asset in SMC_ASSETS:
                self.smc_session._determine_london_direction(asset)

        # ── ETAPE 8 — SMC SESSION : LONDON PULLBACK (10h00 -> 11h30) ─
        if not skip_next and is_time_between("10:00", "11:30"):
            self._check_smc_signals(balance, open_positions)

        # ── ETAPE 9 — STRUCTURE TRAP : TOUS LES ACTIFS ──────────────
        if not skip_next:
            self._check_structure_trap_signals(balance, open_positions)

    # ──────────────────────────────────────────
    # VERIFICATION DES SIGNAUX SMC
    # ──────────────────────────────────────────

    def _check_smc_signals(self, balance: float, open_positions: list) -> None:
        """Verifie et execute les signaux SMC SESSION."""
        for asset in SMC_ASSETS:
            try:
                if not self.risk_manager.is_trade_allowed(open_positions):
                    continue

                if self.pulse_manager.has_rocket_active(asset):
                    continue

                if self.pulse_manager.has_open_position(asset, "SMC_SESSION"):
                    continue

                signal = self.smc_session.run(asset)
                if signal is None:
                    continue

                conviction = "HIGH"
                self._open_trade(signal, asset, conviction)

            except Exception as e:
                logger.error(f"Erreur SMC {asset}: {e}")

    # ──────────────────────────────────────────
    # VERIFICATION DES SIGNAUX STRUCTURE TRAP
    # ──────────────────────────────────────────

    def _check_structure_trap_signals(self, balance: float, open_positions: list) -> None:
        """Verifie et execute les signaux STRUCTURE TRAP."""
        for asset_name, config in MARKET_CONFIG.items():
            try:
                if not self.risk_manager.is_trade_allowed(open_positions):
                    continue

                if not self._is_in_session(asset_name, config):
                    continue

                if self.pulse_manager.has_rocket_active(asset_name):
                    continue

                if self.pulse_manager.has_open_position(asset_name):
                    continue

                signal = self.structure_trap.run(asset_name)
                if signal is None:
                    continue

                conviction = self.smc_session.get_conviction(asset_name, signal["direction"])
                self._open_trade(signal, asset_name, conviction)

            except Exception as e:
                logger.error(f"Erreur StructureTrap {asset_name}: {e}")

    # ──────────────────────────────────────────
    # OUVERTURE DE TRADE
    # ──────────────────────────────────────────

    def _open_trade(self, signal: dict, asset: str, conviction: str) -> None:
        """Ouvre une position et l'enregistre dans le PULSE.

        Args:
            signal: Dict du signal (direction, entry, sl, atr_m1, strategie, reference_mid).
            asset: Nom standard de l'actif.
            conviction: Score de conviction ("HIGH" ou "STANDARD").
        """
        # Calcul du risque et du lot
        balance = self._get_balance()
        risk = self.risk_manager.calculate_risk_for_trade(balance)

        entry_price = signal["entry"]
        sl_price = signal["sl"]
        sl_distance = abs(entry_price - sl_price)

        if sl_distance <= 0:
            logger.warning(f"{asset}: sl_distance nulle, skip")
            return

        point_value = self._estimate_point_value(asset)
        from utils.calculator import calculate_lot_size as calc_lot
        lot_size = calc_lot(risk, sl_distance, point_value)

        if lot_size <= 0:
            logger.warning(f"{asset}: lot calcule a 0, skip")
            return

        # Ouverture de l'ordre
        result = self.order_manager.open_position(
            symbol=asset,
            direction=signal["direction"],
            lot_size=lot_size,
            sl_price=sl_price,
            comment=f"{signal.get('strategie', 'TRAP')[:4]}_{asset}",
            magic=MAGIC_NUMBER,
        )

        if not result or result.get("ticket", 0) == 0:
            logger.error(f"{asset}: echec ouverture position")
            return

        ticket = result["ticket"]

        # Enregistrement dans le PULSE
        pulse_info = {
            "ticket": ticket,
            "actif": asset,
            "direction": signal["direction"],
            "prix_entree": entry_price,
            "sl": sl_price,
            "risk_initial_": risk,
            "etat": "SHIELD",
            "conviction": conviction,
            "strategie": signal.get("strategie", "STRUCTURE_TRAP"),
            "reference_mid": signal.get("reference_mid", 0.0),
        }
        self.pulse_manager.on_position_opened(pulse_info)
        self.risk_manager.on_trade_opened(ticket, risk)

        logger.info(
            f"TRADE OUVERT: {asset} {signal['direction']} "
            f"lot={lot_size:.2f} entry={entry_price:.5f} "
            f"sl={sl_price:.5f} risk={risk:.2f} "
            f"conviction={conviction} ticket={ticket}"
        )

    # ──────────────────────────────────────────
    # UTILITAIRES
    # ──────────────────────────────────────────

    def _is_in_session(self, asset: str, config: dict) -> bool:
        """Verifie si l'actif est dans sa fenetre de trading."""
        contexte = config.get("contexte", "")
        if contexte == "orb":
            return is_time_between(config.get("session_start", "16:00"),
                                   config.get("session_end", "21:45"))
        elif contexte == "asian_box":
            cutoff = config.get("signal_cutoff", "11:30")
            box_start = config.get("asian_box_start", "02:00")
            return is_time_between(box_start, cutoff)
        elif contexte == "bollinger":
            return True
        return True

    def _verify_symbols(self) -> None:
        """Verifie la disponibilite des symboles. Ne pas arreter le bot."""
        all_symbols = list(MARKET_CONFIG.keys())
        logger.info(f"Verification de {len(all_symbols)} symboles...")

        for symbol in all_symbols:
            if not self.data_feed.subscribe_symbol(symbol):
                logger.warning(f"Symbole {symbol} non disponible.")

    def _get_balance(self) -> float:
        """Retourne le solde actuel."""
        if MODE == "PAPER":
            return 10000.0
        return self.mt5.get_balance()

    def _estimate_point_value(self, asset: str) -> float:
        """Estime la valeur d'un point standard pour le calcul de lot."""
        point_values = {
            "EURUSD": 10.0, "GBPUSD": 10.0,
            "XAUUSD": 10.0, "XAGUSD": 50.0,
            "US100": 2.0, "US500": 5.0, "US30": 1.0,
        }
        return point_values.get(asset, 10.0) * 0.01

    def _signal_handler(self, signum, frame) -> None:
        """Gestionnaire de signaux pour un arret propre."""
        logger.info(f"Signal {signum} recu. Arret du bot...")
        self.running = False

    def _shutdown(self) -> None:
        """Arrete proprement tous les composants."""
        logger.info("Arret du bot en cours...")

        if self.order_manager:
            self.order_manager.close_all_positions(reason="BOT_SHUTDOWN")

        if self.mt5:
            self.mt5.disconnect()

        logger.info("Bot arrete proprement.")


if __name__ == "__main__":
    bot = BotOrbStructurePro()
    bot.run()
