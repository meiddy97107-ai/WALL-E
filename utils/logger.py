# -*- coding: utf-8 -*-
"""
logger.py — Systeme de logs avec loguru.

Configuration centralisee des logs avec rotation quotidienne,
niveaux de log standards, et fonctions specialisees pour les
evenements cles du bot.
"""

import sys
from pathlib import Path

from loguru import logger

# ──────────────────────────────────────────────
# CONFIGURATION GLOBALE DU LOGGER
# ──────────────────────────────────────────────

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Supprimer le handler par defaut
logger.remove()

# Format des logs
LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan> | "
    "<level>{message}</level>"
)

# Handler console
logger.add(
    sys.stderr,
    format=LOG_FORMAT,
    level="DEBUG",
    colorize=True,
)

# Handler fichier avec rotation quotidienne
logger.add(
    str(LOG_DIR / "bot_{time:YYYY-MM-DD}.log"),
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name} | {message}",
    level="DEBUG",
    rotation="00:00",
    retention="30 days",
    compression="zip",
    encoding="utf-8",
)


def get_logger(module_name: str = None):
    """Retourne un logger configure pour un module specifique.

    Args:
        module_name: Nom du module (ex: "mt5_connector").

    Returns:
        Instance de logger loguru liee au module.
    """
    if module_name:
        return logger.bind(name=module_name)
    return logger


# ──────────────────────────────────────────────
# FONCTIONS DE LOG SPECIALISEES
# ──────────────────────────────────────────────


def log_trade_opened(actif: str, direction: str, lot: float,
                     entry: float, sl: float, risk_eur: float,
                     strategie: str) -> None:
    """Log l'ouverture d'un trade.

    Args:
        actif: Nom de l'actif.
        direction: "BUY" ou "SELL".
        lot: Taille du lot.
        entry: Prix d'entree.
        sl: Stop loss.
        risk_eur: Montant risque en euros.
        strategie: Strategie utilisee.
    """
    logger.info(
        f"TRADE OPEN | {actif} {direction} | "
        f"Lot={lot:.2f} Entry={entry:.5f} SL={sl:.5f} "
        f"Risk={risk_eur:.2f} Strategy={strategie}"
    )


def log_trade_closed(ticket: int, reason: str, pnl_eur: float) -> None:
    """Log la cloture d'un trade.

    Args:
        ticket: Numero du ticket.
        reason: Raison de la cloture.
        pnl_eur: Profit/Perte en euros.
    """
    label = "PROFIT" if pnl_eur >= 0 else "LOSS"
    logger.info(
        f"TRADE CLOSE | Ticket={ticket} | "
        f"PnL={pnl_eur:+.2f} | Reason={reason} [{label}]"
    )


def log_pulse_state_change(ticket: int, old_state: str, new_state: str) -> None:
    """Log un changement d'etat PULSE.

    Args:
        ticket: Numero du ticket.
        old_state: Ancien etat (SHIELD/TRACKER/ROCKET).
        new_state: Nouvel etat.
    """
    logger.info(
        f"PULSE STATE | Ticket={ticket} | "
        f"{old_state} -> {new_state}"
    )


def log_daily_reset(balance: float, daily_budget: float, phase: str) -> None:
    """Log le reset quotidien.

    Args:
        balance: Solde au moment du reset.
        daily_budget: Budget quotidien calcule.
        phase: Phase detectee (P1/P2/FUNDED).
    """
    logger.info(
        f"DAILY RESET | Balance={balance:.2f} | "
        f"Budget={daily_budget:.2f} | Phase={phase}"
    )


def log_kill_switch(reason: str) -> None:
    """Log l'activation du kill switch.

    Args:
        reason: Raison du kill switch.
    """
    logger.critical(
        f"KILL SWITCH ACTIVATED | Reason: {reason}"
    )
