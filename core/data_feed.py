"""
data_feed.py — Récupération des données temps réel depuis MT5.

Le symbole passé en entrée est toujours le nom standard (ex: "EURUSD").
La conversion vers le nom broker est faite automatiquement via get_symbol().
"""

import pandas as pd
import MetaTrader5 as mt5

from config.settings import MODE, TIMEFRAME_MAP
from config.market_config import get_symbol, get_standard_name
from utils.logger import get_logger

logger = get_logger("data_feed")


class DataFeed:
    """Fournit les données de marché en temps réel depuis MT5."""

    def __init__(self):
        self._subscribed_symbols = set()

    # ──────────────────────────────────────────
    # BOUGIES / CHANDELLES
    # ──────────────────────────────────────────

    def get_candles(self, symbol: str, timeframe: str, count: int = 100) -> pd.DataFrame:
        """Récupère les N dernières bougies pour un symbole.

        Args:
            symbol: Nom standard de l'actif (ex: "EURUSD").
            timeframe: Unité de temps ("M1", "M5", "M15", "H1", "H4", "D1").
            count: Nombre de bougies à récupérer.

        Returns:
            DataFrame avec les colonnes : time, open, high, low, close, tick_volume, spread, real_volume.
        """
        if MODE == "PAPER":
            return self._generate_paper_candles(count)

        broker_symbol = get_symbol(symbol)
        mt5_timeframe = self._get_mt5_timeframe(timeframe)

        try:
            rates = mt5.copy_rates_from_pos(broker_symbol, mt5_timeframe, 0, count)
        except Exception as e:
            logger.error(f"Erreur get_candles pour {symbol} ({broker_symbol}) : {e}")
            return pd.DataFrame()

        if rates is None or len(rates) == 0:
            logger.warning(f"Aucune donnée pour {symbol} ({broker_symbol})")
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df

    def get_candles_between(self, symbol: str, timeframe: str, start: str, end: str) -> pd.DataFrame:
        """Récupère les bougies entre deux heures pour un symbole.

        Args:
            symbol: Nom standard de l'actif.
            timeframe: Unité de temps.
            start: Heure de début au format "HH:MM".
            end: Heure de fin au format "HH:MM".

        Returns:
            DataFrame filtré entre start et end.
        """
        df = self.get_candles(symbol, timeframe, count=2000)
        if df.empty:
            return df

        df["time_str"] = df["time"].dt.strftime("%H:%M")
        mask = (df["time_str"] >= start) & (df["time_str"] <= end)
        return df[mask].drop(columns=["time_str"])

    # ──────────────────────────────────────────
    # PRIX EN TEMPS RÉEL
    # ──────────────────────────────────────────

    def get_current_price(self, symbol: str) -> dict:
        """Récupère le prix actuel d'un symbole.

        Args:
            symbol: Nom standard de l'actif.

        Returns:
            Dict avec bid, ask, spread.
        """
        if MODE == "PAPER":
            return {"bid": 1.1000, "ask": 1.1002, "spread": 0.0002}

        broker_symbol = get_symbol(symbol)

        try:
            tick = mt5.symbol_info_tick(broker_symbol)
            if tick is None:
                logger.warning(f"Impossible de récupérer le tick pour {symbol}")
                return {"bid": 0.0, "ask": 0.0, "spread": 0.0}
            return {
                "bid": tick.bid,
                "ask": tick.ask,
                "spread": tick.ask - tick.bid,
            }
        except Exception as e:
            logger.error(f"Erreur get_current_price pour {symbol} : {e}")
            return {"bid": 0.0, "ask": 0.0, "spread": 0.0}

    def get_spread(self, symbol: str) -> float:
        """Récupère le spread actuel d'un symbole.

        Args:
            symbol: Nom standard de l'actif.

        Returns:
            Valeur du spread en pips/points.
        """
        price = self.get_current_price(symbol)
        return price["spread"]

    # ──────────────────────────────────────────
    # SOUSCRIPTION SYMBOLE
    # ──────────────────────────────────────────

    def subscribe_symbol(self, symbol: str) -> bool:
        """Active le flux temps réel pour un symbole.

        Args:
            symbol: Nom standard de l'actif.

        Returns:
            True si le symbole a été activé avec succès.
        """
        if MODE == "PAPER":
            self._subscribed_symbols.add(symbol)
            return True

        if symbol in self._subscribed_symbols:
            return True

        broker_symbol = get_symbol(symbol)

        try:
            # Activer le symbole dans MT5
            mt5.symbol_select(broker_symbol, True)
            # Vérifier que le symbole est bien disponible
            symbol_info = mt5.symbol_info(broker_symbol)
            if symbol_info is None:
                logger.error(f"Symbole {symbol} ({broker_symbol}) indisponible sur ce broker.")
                return False

            self._subscribed_symbols.add(symbol)
            logger.info(f"Symbole activé : {symbol} → {broker_symbol}")
            return True
        except Exception as e:
            logger.error(f"Erreur subscribe_symbol pour {symbol} : {e}")
            return False

    # ──────────────────────────────────────────
    # MÉTHODES PRIVÉES
    # ──────────────────────────────────────────

    def _get_mt5_timeframe(self, timeframe: str):
        """Convertit un nom de timeframe en constante MT5."""
        mapping = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1,
        }
        return mapping.get(timeframe.upper(), mt5.TIMEFRAME_M1)

    def _generate_paper_candles(self, count: int) -> pd.DataFrame:
        """Génère des données factices pour le mode PAPER."""
        import numpy as np
        from datetime import datetime, timedelta

        now = datetime.now()
        base_price = 1.1000
        data = []
        for i in range(count):
            t = now - timedelta(minutes=count - i)
            noise = np.random.normal(0, 0.001)
            open_p = base_price + noise
            high = open_p + abs(np.random.normal(0, 0.002))
            low = open_p - abs(np.random.normal(0, 0.002))
            close = np.random.uniform(low, high)
            data.append({
                "time": t,
                "open": open_p,
                "high": high,
                "low": low,
                "close": close,
                "tick_volume": np.random.randint(100, 1000),
                "spread": 0.0002,
                "real_volume": 0,
            })
            base_price = close
        return pd.DataFrame(data)
