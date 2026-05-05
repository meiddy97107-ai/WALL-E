"""
data_loader.py — Chargement des donnees historiques depuis MT5.

Charge les bougies M1 directement depuis MT5 via la connexion existante.
Les donnees sont chargees UNE SEULE FOIS au demarrage
et stockees en memoire pour eviter des appels MT5 repetes.
"""

import pandas as pd
import MetaTrader5 as mt5
from datetime import datetime

from config.market_config import get_symbol
from config.settings import ACTIVE_ACCOUNT
from utils.logger import get_logger

logger = get_logger("backtest_data_loader")

# Nombre minimum de bougies pour considerer le chargement valide
MIN_CANDLES_REQUIRED = 100000

TIMEFRAME_MT5 = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}

# Sessions de trading par groupe d'actif
SESSION_FILTERS = {
    "US_INDICES": {"start": "15:30", "end": "22:00"},
    "FOREX": None,  # 24h sauf weekend
    "METALS": None,  # 24h sauf weekend
}


class BacktestDataLoader:
    """Charge les donnees historiques depuis MT5 en une fois."""

    def __init__(self, connector):
        self.connector = connector
        self.broker = ACTIVE_ACCOUNT
        self.cache = {}  # asset -> DataFrame complet

    def load(self, asset: str, start: str, end: str) -> pd.DataFrame:
        """Charge toutes les bougies M1 entre start et end.

        Args:
            asset: Nom standard ("XAUUSD", "EURUSD"...).
            start: Date de debut "2024-05-01".
            end: Date de fin "2025-05-01".

        Returns:
            DataFrame avec colonnes [time, open, high, low, close, tick_volume, spread].

        Raises:
            ValueError si moins de 100000 bougies.
        """
        if not self.connector.is_connected():
            raise ConnectionError("MT5 doit etre connecte pour charger les donnees historiques.")

        broker_symbol = get_symbol(asset, self.broker)
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")

        logger.info(f"Chargement {asset} ({broker_symbol}) du {start} au {end}...")

        # Chargement par lots pour eviter les limites MT5
        all_frames = []
        current_start = start_dt
        BATCH_DAYS = 30

        while current_start < end_dt:
            current_end = min(current_start + pd.Timedelta(days=BATCH_DAYS), end_dt)
            ts_start = int(current_start.timestamp())
            ts_end = int(current_end.timestamp())
            rates = mt5.copy_rates_range(
                broker_symbol,
                mt5.TIMEFRAME_M1,
                ts_start,
                ts_end,
            )
            if rates is not None and len(rates) > 0:
                df_batch = pd.DataFrame(rates)
                all_frames.append(df_batch)
                logger.debug(f"Lot charge: {current_start.date()} -> {current_end.date()}: {len(rates)} bougies")
            else:
                logger.warning(f"Aucune donnee du {current_start.date()} au {current_end.date()}")
            current_start = current_end

        if not all_frames:
            raise ValueError(
                f"Donnees insuffisantes pour {asset}: {total_candles} bougies "
                f"(minimum requis: {MIN_CANDLES_REQUIRED}). "
                f"Verifie que MT5 a les donnees historiques pour cette periode."
            )

        df = pd.concat(all_frames, ignore_index=True)

        try:
            df["time"] = pd.to_datetime(df["time"], unit="s")

            # Filtrer les weekends
            df = df[df["time"].dt.dayofweek < 5].copy()

            # Filtrer les sessions pour les indices
            config = self._get_asset_group(asset)
            session_filter = SESSION_FILTERS.get(config)
            if session_filter is not None:
                df["time_str"] = df["time"].dt.strftime("%H:%M")
                start_h, start_m = map(int, session_filter["start"].split(":"))
                end_h, end_m = map(int, session_filter["end"].split(":"))
                start_min = start_h * 60 + start_m
                end_min = end_h * 60 + end_m
                df_minutes = df["time"].dt.hour * 60 + df["time"].dt.minute
                if start_min <= end_min:
                    df = df[(df_minutes >= start_min) & (df_minutes <= end_min)].copy()
                else:
                    df = df[(df_minutes >= start_min) | (df_minutes <= end_min)].copy()
                df = df.drop(columns=["time_str"])

            df = df.reset_index(drop=True)

            # Mettre l'heure de Paris
            df["time"] = pd.to_datetime(df["time"]).dt.tz_localize("UTC").dt.tz_convert("Europe/Paris")
            df["time"] = df["time"].dt.tz_localize(None)

        except Exception as e:
            logger.error(f"Erreur lors du post-traitement des donnees {asset}: {e}")
            logger.error(f"Shape: {df.shape}, colonnes: {list(df.columns)}")
            if not df.empty:
                logger.error(f"Premiere ligne: {df.iloc[0].to_dict()}")
            raise

        self.cache[asset] = df

        logger.info(
            f"Charge: {asset} -> {len(df)} bougies, "
            f"du {df['time'].iloc[0]} au {df['time'].iloc[-1]}"
        )

        return df

    def load_multi_timeframe(self, asset: str, start: str, end: str) -> dict:
        """Charge M1, M5, M15, H1 pour un actif.

        Retourne un dict { "M1": DataFrame, "M5": DataFrame, ... }.
        """
        if not self.connector.is_connected():
            raise ConnectionError("MT5 doit etre connecte.")

        broker_symbol = get_symbol(asset, self.broker)
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")

        result = {}
        for tf_name, tf_mt5 in TIMEFRAME_MT5.items():
            rates = mt5.copy_rates_range(
                broker_symbol, tf_mt5,
                start_dt.timestamp(), end_dt.timestamp()
            )
            if rates is not None and len(rates) > 0:
                df = pd.DataFrame(rates)
                df["time"] = pd.to_datetime(df["time"], unit="s")
                df = df[df["time"].dt.dayofweek < 5].copy()
                df["time"] = df["time"].dt.tz_localize("UTC").dt.tz_convert("Europe/Paris")
                df["time"] = df["time"].dt.tz_localize(None)
                df = df.reset_index(drop=True)
                result[tf_name] = df

        logger.info(f"Multi-timeframe charge pour {asset}: {list(result.keys())}")
        return result

    def get_spread_stats(self, asset: str) -> dict:
        """Calcule les statistiques de spread sur les donnees chargees.

        Returns:
            Dict avec mean, max, p95.
        """
        df = self.cache.get(asset)
        if df is None or df.empty:
            return {"mean": 0.0, "max": 0.0, "p95": 0.0}

        spreads = df["spread"].values
        return {
            "mean": float(spreads.mean()),
            "max": float(spreads.max()),
            "p95": float(pd.Series(spreads).quantile(0.95)),
        }

    def get_loaded_data(self, asset: str) -> pd.DataFrame | None:
        """Retourne les donnees deja chargees pour un actif."""
        return self.cache.get(asset)

    def _get_asset_group(self, asset: str) -> str | None:
        """Retourne le groupe de l'actif pour le filtrage de session."""
        from config.market_config import MARKET_CONFIG
        config = MARKET_CONFIG.get(asset, {})
        return config.get("groupe")
