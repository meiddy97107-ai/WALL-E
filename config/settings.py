"""
settings.py — Chargement du .env et constantes globales.

Détermine quel compte est actif (VT_MARKETS ou THE5ERS)
et expose toutes les constantes globales du bot.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Charger le .env depuis la racine du projet
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

# ──────────────────────────────────────────────
# MODE D'EXÉCUTION
# ──────────────────────────────────────────────
MODE = os.getenv("MODE", "LIVE")  # LIVE | BACKTEST | PAPER

# ──────────────────────────────────────────────
# COMPTE ACTIF
# ──────────────────────────────────────────────
ACTIVE_ACCOUNT = os.getenv("ACTIVE_ACCOUNT", "")

# ──────────────────────────────────────────────
# SÉLECTION DES CREDENTIALS SELON LE COMPTE ACTIF
# ──────────────────────────────────────────────
def _safe_int(value: str, default: int = 0) -> int:
    """Convertit une chaîne en int, retourne la valeur par défaut si vide ou invalide."""
    if not value or not value.strip():
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _get_credentials() -> dict:
    if ACTIVE_ACCOUNT == "VT_MARKETS":
        return {
            "login": _safe_int(os.getenv("VT_LOGIN")),
            "password": os.getenv("VT_PASSWORD", ""),
            "server": os.getenv("VT_SERVER", ""),
        }
    elif ACTIVE_ACCOUNT == "THE5ERS":
        return {
            "login": _safe_int(os.getenv("THE5ERS_LOGIN")),
            "password": os.getenv("THE5ERS_PASSWORD", ""),
            "server": os.getenv("THE5ERS_SERVER", ""),
        }
    else:
        raise ValueError(
            f"ACTIVE_ACCOUNT invalide : {ACTIVE_ACCOUNT}. "
            f"Les valeurs possibles sont 'VT_MARKETS' ou 'THE5ERS'."
        )


def get_credentials() -> dict:
    """Retourne les credentials du compte actif. Sans levée d'exception au chargement."""
    try:
        return _get_credentials()
    except ValueError as e:
        from utils.logger import get_logger
        get_logger("settings").warning(f"Credentials non disponibles : {e}")
        return {"login": 0, "password": "", "server": ""}


CREDENTIALS = get_credentials()

# ──────────────────────────────────────────────
# PARAMÈTRES MT5
# ──────────────────────────────────────────────
MT5_PATH = os.getenv("MT5_PATH", r"C:\Program Files\MetaTrader 5\terminal64.exe")
MT5_TIMEOUT = int(os.getenv("MT5_TIMEOUT", "30000"))
MT5_AUTO_LAUNCH = os.getenv("MT5_AUTO_LAUNCH", "true").lower() == "true"
MT5_RETRY_COUNT = int(os.getenv("MT5_RETRY_COUNT", "3"))
MT5_RETRY_DELAY = int(os.getenv("MT5_RETRY_DELAY", "5"))

# ──────────────────────────────────────────────
# CHALLENGE
# ──────────────────────────────────────────────
CHALLENGE_START_BALANCE = float(os.getenv("CHALLENGE_START_BALANCE", "0.0"))

# ──────────────────────────────────────────────
# MAGIC NUMBER DU BOT
# ──────────────────────────────────────────────
MAGIC_NUMBER = 123456

# ──────────────────────────────────────────────
# CONSTANTES GLOBALES
# ──────────────────────────────────────────────
DAILY_RISK_PERCENT = 4.0  # 4% du solde par jour
DEFAULT_TIMEFRAMES = ["M1", "M5", "M15", "H1", "H4", "D1"]

TIMEFRAME_MAP = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}

# ──────────────────────────────────────────────
# BROKER NAME HELPER
# ──────────────────────────────────────────────
def get_broker_name() -> str:
    """Retourne le nom du broker actif pour la conversion des symboles."""
    return ACTIVE_ACCOUNT
