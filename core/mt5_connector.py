"""
mt5_connector.py — Connexion MT5 avec auto-launch, retry et vérification permanente.

C'est le module le plus critique du bot. Il gère :
- L'auto-démarrage de MT5 si le processus n'est pas lancé
- La connexion avec les credentials du .env
- Le retry automatique en cas d'échec
- La vérification continue de la connexion
- Le shutdown propre
"""

import time
import subprocess
from pathlib import Path

import MetaTrader5 as mt5

from config.settings import (
    CREDENTIALS,
    MT5_PATH,
    MT5_TIMEOUT,
    MT5_AUTO_LAUNCH,
    MT5_RETRY_COUNT,
    MT5_RETRY_DELAY,
    MODE,
)
from utils.logger import get_logger

logger = get_logger("mt5_connector")


class MT5Connector:
    """Gère la connexion à MetaTrader 5 avec auto-launch et mécanisme de retry."""

    def __init__(self):
        self._connected = False
        self._account_info = None

    # ──────────────────────────────────────────
    # CONNEXION
    # ──────────────────────────────────────────

    def connect(self) -> bool:
        """Établit la connexion à MT5.

        Si MT5 n'est pas lancé et que MT5_AUTO_LAUNCH est True,
        démarre automatiquement le terminal.

        Returns:
            True si la connexion a réussi, False sinon.
        """
        if MODE == "PAPER":
            logger.info("[PAPER MODE] Connexion MT5 simulée — aucun appel réel effectué.")
            self._connected = True
            return True

        logger.info("Tentative de connexion à MetaTrader 5...")

        # Vérifier si MT5 est déjà lancé
        if not self._is_mt5_running():
            if MT5_AUTO_LAUNCH:
                self._launch_mt5()
            else:
                logger.error("MT5 n'est pas lancé et AUTO_LAUNCH est désactivé.")
                return False

        # Attendre que MT5 soit prêt
        self._wait_for_ready()

        # Tentatives de connexion
        for attempt in range(1, MT5_RETRY_COUNT + 1):
            try:
                initialized = mt5.initialize(
                    path=MT5_PATH,
                    login=CREDENTIALS["login"],
                    password=CREDENTIALS["password"],
                    server=CREDENTIALS["server"],
                    timeout=MT5_TIMEOUT,
                )
            except Exception as e:
                logger.error(f"Exception MT5.initialize (tentative {attempt}/{MT5_RETRY_COUNT}): {e}")
                initialized = False

            if initialized:
                self._connected = True
                self._account_info = self.get_account_info()
                logger.info(
                    f"Connecté à MT5 — Compte: {self._account_info.get('login')}, "
                    f"Solde: {self._account_info.get('balance')}"
                )
                return True

            logger.warning(
                f"Échec connexion (tentative {attempt}/{MT5_RETRY_COUNT}). "
                f"Nouvelle tentative dans {MT5_RETRY_DELAY}s..."
            )
            time.sleep(MT5_RETRY_DELAY)

        logger.error("Connexion à MT5 impossible après toutes les tentatives.")
        # Dernière chance : réinitialiser MT5 et réessayer une fois
        mt5.shutdown()
        time.sleep(1)
        try:
            initialized = mt5.initialize(
                path=MT5_PATH,
                login=CREDENTIALS["login"],
                password=CREDENTIALS["password"],
                server=CREDENTIALS["server"],
                timeout=MT5_TIMEOUT,
            )
            if initialized:
                self._connected = True
                self._account_info = self.get_account_info()
                logger.info("Connexion réussie après réinitialisation MT5.")
                return True
        except Exception as e:
            logger.error(f"Échec après réinitialisation : {e}")

        return False

    def disconnect(self) -> None:
        """Ferme proprement la connexion MT5."""
        if MODE == "PAPER":
            logger.info("[PAPER MODE] Déconnexion simulée.")
            self._connected = False
            return

        try:
            mt5.shutdown()
            self._connected = False
            logger.info("Connexion MT5 fermée proprement.")
        except Exception as e:
            logger.error(f"Erreur lors de la déconnexion MT5 : {e}")

    # ──────────────────────────────────────────
    # VÉRIFICATION DE LA CONNEXION
    # ──────────────────────────────────────────

    def is_connected(self) -> bool:
        """Vérifie que la connexion MT5 est toujours active.

        Returns:
            True si connecté, False sinon.
        """
        if MODE == "PAPER":
            return self._connected

        try:
            terminal_info = mt5.terminal_info()
            if terminal_info is None:
                self._connected = False
                return False
            self._connected = terminal_info.connected
            return self._connected
        except Exception:
            self._connected = False
            return False

    def reconnect(self) -> bool:
        """Tente une reconnexion automatique.

        Returns:
            True si la reconnexion a réussi, False sinon.
        """
        logger.warning("Tentative de reconnexion MT5...")
        self.disconnect()
        time.sleep(2)
        return self.connect()

    # ──────────────────────────────────────────
    # INFORMATIONS COMPTE
    # ──────────────────────────────────────────

    def get_account_info(self) -> dict:
        """Retourne les informations du compte connecté.

        Returns:
            Dict avec les infos du compte, ou dict vide si erreur.
        """
        if MODE == "PAPER":
            return {"login": 0, "balance": 10000.0, "equity": 10000.0}

        try:
            account_info = mt5.account_info()
            if account_info is None:
                logger.error("Impossible de récupérer les infos du compte MT5.")
                return {}
            return {
                "login": account_info.login,
                "balance": account_info.balance,
                "equity": account_info.equity,
                "currency": account_info.currency,
                "leverage": account_info.leverage,
                "name": account_info.name,
                "server": account_info.server,
                "margin_free": account_info.margin_free,
                "margin": account_info.margin,
                "profit": account_info.profit,
            }
        except Exception as e:
            logger.error(f"Erreur get_account_info : {e}")
            return {}

    def get_balance(self) -> float:
        """Retourne le solde actuel du compte."""
        info = self.get_account_info()
        return info.get("balance", 0.0)

    def get_equity(self) -> float:
        """Retourne les capitaux propres actuels."""
        info = self.get_account_info()
        return info.get("equity", 0.0)

    # ──────────────────────────────────────────
    # MÉTHODES PRIVÉES
    # ──────────────────────────────────────────

    def _is_mt5_running(self) -> bool:
        """Vérifie si le processus MT5 est en cours d'exécution."""
        try:
            result = mt5.initialize()
            if result:
                mt5.shutdown()
                return True
            return False
        except Exception:
            return False

    def _launch_mt5(self) -> None:
        """Lance MT5 via le chemin exécutable du .env."""
        mt5_path = Path(MT5_PATH)
        if not mt5_path.exists():
            logger.error(f"Exécutable MT5 introuvable : {MT5_PATH}")
            return

        logger.info(f"Lancement de MT5 : {MT5_PATH}")
        try:
            subprocess.Popen([str(mt5_path)], shell=True)
            logger.info("MT5 lancé. Attente du démarrage...")
        except Exception as e:
            logger.error(f"Erreur lors du lancement de MT5 : {e}")

    def _wait_for_ready(self) -> None:
        """Attend que MT5 soit prêt (timeout configurable)."""
        logger.info(f"Attente de disponibilité MT5 ({MT5_TIMEOUT}ms max)...")
        time.sleep(min(MT5_TIMEOUT / 1000, 10))
