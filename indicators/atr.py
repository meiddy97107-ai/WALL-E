"""
atr.py — Calcul de l'Average True Range (ATR).

Utilisé par le système PULSE pour les transitions d'état (Shield → Tracker → Rocket),
le filtrage des signaux, et le placement des stops.
"""

import pandas as pd
import numpy as np


def calculate_atr(candles: pd.DataFrame, period: int = 14) -> float:
    """Calcule l'ATR sur les N dernières bougies.

    L'ATR mesure la volatilité du marché en calculant la moyenne des
    vraies amplitudes (True Range) sur la période donnée.

    Args:
        candles: DataFrame avec colonnes high, low, close.
        period: Période de calcul de l'ATR (défaut: 14).

    Returns:
        Valeur ATR actuelle. Retourne 0.0 si données insuffisantes.
    """
    if candles.empty or len(candles) < period + 1:
        return 0.0

    high = candles["high"].values
    low = candles["low"].values
    close = candles["close"].values

    # True Range pour chaque bougie
    tr = np.zeros(len(candles))
    for i in range(1, len(candles)):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )

    # ATR = moyenne mobile simple des True Range
    atr = np.mean(tr[-period:])
    return float(atr)


def get_atr_series(candles: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calcule la série complète d'ATR pour les comparaisons historiques.

    Utilise une moyenne mobile pour lisser les valeurs d'ATR sur toute
    la période disponible.

    Args:
        candles: DataFrame avec colonnes high, low, close.
        period: Période de calcul (défaut: 14).

    Returns:
        Series pandas avec les valeurs d'ATR historiques.
    """
    if candles.empty or len(candles) < period + 1:
        return pd.Series(dtype=float)

    high = candles["high"].values
    low = candles["low"].values
    close = candles["close"].values

    tr = np.zeros(len(candles))
    for i in range(1, len(candles)):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )

    # ATR lissé (Wilder smoothing)
    atr_values = np.zeros(len(candles))
    atr_values[period] = np.mean(tr[1 : period + 1])
    for i in range(period + 1, len(candles)):
        atr_values[i] = (atr_values[i - 1] * (period - 1) + tr[i]) / period

    return pd.Series(atr_values)


def get_atr_mean(candles: pd.DataFrame, period: int = 14, lookback: int = 20) -> float:
    """Calcule l'ATR moyen sur les N dernières valeurs.

    Utilisé par l'état ROCKET pour détecter une expansion de volatilité
    en comparant l'ATR actuel à sa moyenne récente.

    Args:
        candles: DataFrame avec colonnes high, low, close.
        period: Période de calcul de l'ATR (défaut: 14).
        lookback: Nombre de valeurs ATR à moyenner (défaut: 20).

    Returns:
        Moyenne des ATR récents. Retourne 0.0 si données insuffisantes.
    """
    atr_series = get_atr_series(candles, period)
    if atr_series.empty or len(atr_series) < lookback:
        return 0.0

    return float(atr_series.iloc[-lookback:].mean())
