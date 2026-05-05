"""
backtest_data_feed.py — DataFeed pour le backtest.

Remplace DataFeed pendant le backtest.
Utilise les donnees pre-chargees au lieu d'interroger MT5.
"""

import pandas as pd
from datetime import datetime

from utils.logger import get_logger

logger = get_logger("backtest_data_feed")


class BacktestDataFeed:
    """Simule DataFeed pour le backtest avec donnees pre-chargees.

    Les donnees sont chargees une fois au demarrage du backtest
    et servies depuis la memoire. A chaque appel, on slice
    les donnees jusqu'a l'index courant (anti-look-ahead).
    """

    def __init__(self):
        self._data = {}  # timeframe -> DataFrame complet
        self._current_index = {}  # timeframe -> index courant
        self._current_price = {"bid": 0.0, "ask": 0.0, "spread": 0.0}

    def set_data(self, data: dict) -> None:
        """Injecte les donnees pre-chargees.

        Args:
            data: Dict { "M1": DataFrame, "M5": DataFrame, ... }
        """
        self._data = data
        for tf in data:
            self._current_index[tf] = 0

    def set_current_index(self, index: int, timeframe: str = "M1") -> None:
        """Definit l'index courant pour eviter le look-ahead.

        Args:
            index: Index jusqu'auquel on peut lire.
            timeframe: Timeframe concerne.
        """
        self._current_index[timeframe] = index

    def set_time(self, current_time: datetime) -> None:
        """Met a jour les index de tous les timeframes en fonction d'une date/heure.

        Chaque timeframe avance jusqu'a la bougie dont le time <= current_time.
        Garantit l'anti-look-ahead sur TOUS les timeframes simultanement.

        Args:
            current_time: Date/heure de la bougie M1 courante.
        """
        for tf_name, df in self._data.items():
            if df is None or df.empty:
                continue
            # Trouver la derniere bougie avec time <= current_time
            # Les times sont tries par ordre chronologique
            mask = df["time"] <= current_time
            idx = mask.sum()  # Nombre de bougies <= current_time
            self._current_index[tf_name] = idx

    def get_candles(self, symbol: str, timeframe: str, count: int = 100) -> pd.DataFrame:
        """Retourne les N dernieres bougies jusqu'a l'index courant.

        Args:
            symbol: Ignore (toujours l'actif du backtest).
            timeframe: Unite de temps.
            count: Nombre de bougies.

        Returns:
            DataFrame avec les bougies.
        """
        df = self._data.get(timeframe)
        if df is None or df.empty:
            return pd.DataFrame()

        idx = self._current_index.get(timeframe, len(df))
        start = max(0, idx - count)
        return df.iloc[start:idx].copy()

    def get_current_price(self, symbol: str) -> dict:
        """Retourne le dernier prix connu."""
        df = self._data.get("M1")
        if df is not None and not df.empty:
            idx = self._current_index.get("M1", len(df))
            if idx > 0 and idx <= len(df):
                candle = df.iloc[idx - 1]
                return {
                    "bid": float(candle["close"]),
                    "ask": float(candle["close"]),
                    "spread": float(candle.get("spread", 0)),
                }
        return self._current_price

    def set_current_price(self, price: float) -> None:
        """Definit le prix courant pour get_current_price()."""
        self._current_price = {"bid": price, "ask": price, "spread": 0.0}

    def get_spread(self, symbol: str) -> float:
        return self._current_price.get("spread", 0.0)

    def subscribe_symbol(self, symbol: str) -> bool:
        return True
