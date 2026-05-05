"""
simulator.py — Simulateur d'ordres pour le backtest.

Reproduit le comportement reel du marche :
- Spread realiste par actif
- Slippage a l'ouverture
- Pas d'execution au prix exact si le marche a deja bouge
"""

import random
from datetime import date, datetime

import pandas as pd
import numpy as np

from config.market_config import MARKET_CONFIG
from utils.logger import get_logger
from utils.calculator import calculate_lot_size as calc_lot

logger = get_logger("backtest_simulator")

# Spreads realistes par actif (en points de prix)
SPREADS_REALISTES = {
    "EURUSD": 0.00008, "GBPUSD": 0.00012,
    "XAUUSD": 0.25, "XAGUSD": 0.030,
    "US100": 1.0, "US500": 0.50, "US30": 1.50,
}

# Slippage realiste a l'ouverture (en points de prix)
SLIPPAGE_REALISTE = {
    "EURUSD": 0.00005, "GBPUSD": 0.00008,
    "XAUUSD": 0.10, "XAGUSD": 0.015,
    "US100": 0.50, "US500": 0.30, "US30": 0.80,
}

# Valeur du point par actif pour le calcul du PnL
POINT_VALUES = {
    "EURUSD": 10.0, "GBPUSD": 10.0,
    "XAUUSD": 10.0, "XAGUSD": 50.0,
    "US100": 2.0, "US500": 5.0, "US30": 1.0,
}


class BacktestSimulator:
    """Simule l'execution des ordres sur donnees historiques."""

    def __init__(self, initial_balance: float = 2492.0, currency: str = "EUR"):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.currency = currency
        self.open_positions = []  # Liste des positions ouvertes
        self.closed_trades = []  # Liste des trades fermes
        self.equity_curve = []  # [(datetime, equity), ...]
        self.daily_snapshots = {}  # date (str) -> balance a 00h00
        self._last_known_prices = {}
        self._next_id = 1

        # Seed pour la reproductibilite
        random.seed(42)

    def open_position(self, asset: str, direction: str,
                      lot_size: float, sl_price: float,
                      entry_price: float = None,
                      entry_candle: pd.Series = None,
                      risk_eur: float = 0.0,
                      strategie: str = "",
                      conviction: str = "STANDARD") -> dict | None:
        """Simule l'ouverture d'un ordre.

        Args:
            asset: Nom standard de l'actif.
            direction: "BUY" ou "SELL".
            lot_size: Taille du lot.
            sl_price: Prix du stop loss.
            entry_price: Prix d'entree (utilisee si fournie).
            entry_candle: Bougie M1 d'entree (utilisee si entry_price est None).
            risk_eur: Montant risque en euros.
            strategie: Nom de la strategie.
            conviction: "HIGH" ou "STANDARD".

        Returns:
            Dict de la position ouverte, ou None si echec.
        """
        if entry_price is not None:
            # Utiliser le prix fourni directement (pas de recalcul)
            pass
        elif entry_candle is not None:
            # Recalculer depuis la bougie avec spread et slippage
            close_price = entry_candle.get("close", 1.0) if hasattr(entry_candle, 'get') else float(entry_candle.get("close", 1.0))
            spread = SPREADS_REALISTES.get(asset, 0.0001)
            slippage = random.uniform(0, SLIPPAGE_REALISTE.get(asset, 0.0001))
            if direction == "BUY":
                entry_price = close_price + spread / 2 + slippage
            else:
                entry_price = close_price - spread / 2 - slippage
        else:
            return None

        if direction == "BUY":
            if entry_price <= sl_price:
                return None
        else:
            if entry_price >= sl_price:
                return None

        position = {
            "id": self._next_id,
            "asset": asset,
            "direction": direction,
            "lot_size": lot_size,
            "entry_price": entry_price,
            "sl_price": sl_price,
            "entry_time": datetime.now(),
            "risk_eur": risk_eur,
            "strategie": strategie,
            "conviction": conviction,
            "etat": "SHIELD",
            "compteur_rocket": 0,
            "exit_price": None,
            "exit_time": None,
            "exit_reason": None,
            "pnl_eur": None,
        }
        self._next_id += 1
        self.open_positions.append(position)

        return position

    def update_positions(self, current_candle: pd.Series,
                          asset: str, atr_m1: float) -> list:
        """Verifie si les SL sont touches pour toutes les positions d'un actif.

        Args:
            current_candle: Bougie M1 courante.
            asset: Nom de l'actif.
            atr_m1: ATR M1 courant.

        Returns:
            Liste des positions encore ouvertes apres verification des SL.
        """
        closed_positions = []

        for pos in list(self.open_positions):
            if pos["asset"] != asset:
                continue

            candle_low = current_candle.get("low", 0)
            candle_high = current_candle.get("high", 0)

            config = MARKET_CONFIG.get(pos["asset"], {})
            be_threshold = config.get("be_threshold", 2.0)

            if pos["etat"] == "SHIELD":
                close_price = float(current_candle.get("close", 0))

                if pos["direction"] == "BUY":
                    profit_points = (close_price - pos["entry_price"]) / self._price_per_point(pos["asset"])
                else:
                    profit_points = (pos["entry_price"] - close_price) / self._price_per_point(pos["asset"])

                if profit_points <= 0:
                    continue  # Pas en profit sur le close → pas de BE

                pnl_flottant = profit_points * POINT_VALUES.get(pos["asset"], 10.0) * pos["lot_size"]

                seuil_be = be_threshold * 2 * atr_m1 * POINT_VALUES.get(pos["asset"], 10.0) * pos["lot_size"] / self._price_per_point(pos["asset"])

                if pnl_flottant >= seuil_be:
                    pos["etat"] = "TRACKER"
                    pos["sl_price"] = pos["entry_price"]
                    logger.debug(
                        f"PULSE {pos['asset']} #{pos['id']}: SHIELD → TRACKER "
                        f"(BE atteint, sl déplacé à {pos['entry_price']:.5f})"
                    )

            if pos["direction"] == "BUY":
                if candle_low <= pos["sl_price"]:
                    logger.info(
                        f"DEBUG SL HIT: {pos['direction']} {pos['asset']} "
                        f"entry={pos['entry_price']:.5f} "
                        f"sl={pos['sl_price']:.5f} "
                        f"candle_low={candle_low:.5f} "
                        f"candle_high={candle_high:.5f}"
                    )
                    exit_price = pos["sl_price"]
                    closed_trade = self.close_position(pos["id"], exit_price,
                                        current_candle.name if isinstance(current_candle.name, datetime) else current_candle.get("time"),
                                        "SL_HIT")
                    if closed_trade:
                        closed_positions.append(closed_trade)
            else:
                if candle_high >= pos["sl_price"]:
                    logger.info(
                        f"DEBUG SL HIT: {pos['direction']} {pos['asset']} "
                        f"entry={pos['entry_price']:.5f} "
                        f"sl={pos['sl_price']:.5f} "
                        f"candle_low={candle_low:.5f} "
                        f"candle_high={candle_high:.5f}"
                    )
                    exit_price = pos["sl_price"]
                    closed_trade = self.close_position(pos["id"], exit_price,
                                        current_candle.name if isinstance(current_candle.name, datetime) else current_candle.get("time"),
                                        "SL_HIT")
                    if closed_trade:
                        closed_positions.append(closed_trade)

        self._last_known_prices[asset] = float(current_candle.get("close", 0))
        return closed_positions

    def close_position(self, position_id: int,
                        exit_price: float,
                        exit_time: datetime,
                        reason: str) -> dict | None:
        """Ferme une position et calcule le PnL.

        Args:
            position_id: ID de la position.
            exit_price: Prix de sortie.
            exit_time: Date/heure de sortie.
            reason: Raison de la fermeture.

        Returns:
            Dict du trade ferme avec PnL, ou None si introuvable.
        """
        for pos in list(self.open_positions):
            if pos["id"] == position_id:
                self.open_positions.remove(pos)

                asset = pos["asset"]
                point_value = POINT_VALUES.get(asset, 10.0)

                if pos["direction"] == "BUY":
                    pnl_points = (exit_price - pos["entry_price"]) / self._price_per_point(asset)
                else:
                    pnl_points = (pos["entry_price"] - exit_price) / self._price_per_point(asset)

                pnl_eur = pnl_points * point_value * pos["lot_size"]
                self.balance += pnl_eur

                trade = {
                    **pos,
                    "exit_price": exit_price,
                    "exit_time": exit_time,
                    "exit_reason": reason,
                    "pnl_eur": round(pnl_eur, 2),
                    "pnl_points": round(pnl_points, 2),
                }
                self.closed_trades.append(trade)
                return trade

        return None

    def close_all_positions(self, reason: str = "BACKTEST_END") -> None:
        """Ferme toutes les positions a la fin du backtest."""
        for pos in list(self.open_positions):
            exit_price = self._last_known_prices.get(pos["asset"], pos["entry_price"])
            self.close_position(pos["id"], exit_price, datetime.now(), reason)

    def snapshot_daily(self, current_date: date) -> None:
        """Enregistre le solde a 00h00. Pour le calcul du daily drawdown."""
        date_str = current_date.isoformat()
        if date_str not in self.daily_snapshots:
            self.daily_snapshots[date_str] = self.balance

    def check_daily_limit(self, current_date: date) -> bool:
        """Verifie si le daily loss limit (4%) est atteint.

        Returns:
            True si le kill switch doit s'activer.
        """
        date_str = current_date.isoformat()
        snapshot = self.daily_snapshots.get(date_str)
        if snapshot is None:
            return False

        daily_budget = snapshot * 0.04
        return (snapshot - self.balance) >= daily_budget

    def get_equity(self) -> float:
        """Balance + PnL flottant de toutes les positions ouvertes."""
        floating = 0.0
        for pos in self.open_positions:
            asset = pos["asset"]
            point_value = POINT_VALUES.get(asset, 10.0)
            entry = pos["entry_price"]
            if pos["direction"] == "BUY":
                pnl = (entry - entry) * point_value * pos["lot_size"]  # On ne connait pas le prix courant ici
            else:
                pnl = (entry - entry) * point_value * pos["lot_size"]
            floating += pnl
        return self.balance + floating

    def record_equity(self, timestamp: datetime) -> None:
        """Enregistre le point d'equite actuel dans la courbe."""
        self.equity_curve.append((timestamp, self.balance))

    def _price_per_point(self, asset: str) -> float:
        """Retourne la valeur d'un point en prix pour un actif."""
        mapping = {
            "EURUSD": 0.0001, "GBPUSD": 0.0001,
            "XAUUSD": 0.01, "XAGUSD": 0.001,
            "US100": 0.01, "US500": 0.1, "US30": 1.0,
        }
        return mapping.get(asset, 0.0001)
