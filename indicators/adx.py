"""
adx.py — Calcul de l'Average Directional Index (ADX).

Utilisé comme filtre de tendance par les stratégies SMC.
ADX > 20 = tendance (forte direction).
ADX < 20 = range (pas de direction claire).
"""

import pandas as pd
import numpy as np


def calculate_adx(candles: pd.DataFrame, period: int = 14) -> float:
    """Calcule l'ADX (Average Directional Index).

    L'ADX mesure la force d'une tendance sans en indiquer la direction.
    - ADX > 25 : tendance forte
    - ADX > 20 : tendance modérée
    - ADX < 20 : marché range/faible

    Args:
        candles: DataFrame avec colonnes high, low, close.
        period: Période de calcul (défaut: 14).

    Returns:
        Valeur ADX actuelle. Retourne 0.0 si données insuffisantes.
    """
    if candles.empty or len(candles) < period + 1:
        return 0.0

    high = candles["high"].values
    low = candles["low"].values
    close = candles["close"].values

    n = len(candles)

    # Directional Movement
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)

    for i in range(1, n):
        # True Range
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )

        # Directional Movement
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]

        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        else:
            plus_dm[i] = 0.0

        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move
        else:
            minus_dm[i] = 0.0

    # Lissage Wilder (EMA-like)
    atr = np.zeros(n)
    plus_di = np.zeros(n)
    minus_di = np.zeros(n)
    dx = np.zeros(n)

    # Première valeur = SMA
    atr[period] = np.mean(tr[1 : period + 1])
    plus_di[period] = 100 * np.mean(plus_dm[1 : period + 1]) / atr[period] if atr[period] != 0 else 0
    minus_di[period] = 100 * np.mean(minus_dm[1 : period + 1]) / atr[period] if atr[period] != 0 else 0

    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
        plus_di[i] = (
            (plus_di[i - 1] * (period - 1) + 100 * plus_dm[i] / atr[i]) / period
            if atr[i] != 0
            else 0
        )
        minus_di[i] = (
            (minus_di[i - 1] * (period - 1) + 100 * minus_dm[i] / atr[i]) / period
            if atr[i] != 0
            else 0
        )

        # Directional Index
        di_sum = plus_di[i] + minus_di[i]
        di_diff = abs(plus_di[i] - minus_di[i])
        dx[i] = 100 * di_diff / di_sum if di_sum != 0 else 0

    # ADX = moyenne des DX
    adx = np.zeros(n)
    adx[period * 2 - 1] = np.mean(dx[period : period * 2])
    for i in range(period * 2, n):
        adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

    return float(adx[-1])


def get_directional_indicators(candles: pd.DataFrame, period: int = 14) -> dict:
    """Retourne les indicateurs directionnels complets (ADX, +DI, -DI).

    +DI et -DI indiquent la direction de la tendance :
    - +DI > -DI : pression haussière dominante
    - -DI > +DI : pression baissière dominante

    Args:
        candles: DataFrame avec colonnes high, low, close.
        period: Période de calcul (défaut: 14).

    Returns:
        Dict avec adx, plus_di, minus_di.
    """
    if candles.empty or len(candles) < period * 2:
        return {"adx": 0.0, "plus_di": 0.0, "minus_di": 0.0}

    high = candles["high"].values
    low = candles["low"].values
    close = candles["close"].values

    n = len(candles)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)

    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        plus_dm[i] = up_move if up_move > down_move and up_move > 0 else 0.0
        minus_dm[i] = down_move if down_move > up_move and down_move > 0 else 0.0

    atr_last = np.mean(tr[-period:]) if len(tr) >= period else np.mean(tr[1:])
    plus_di_last = 100 * np.mean(plus_dm[-period:]) / atr_last if atr_last != 0 else 0
    minus_di_last = 100 * np.mean(minus_dm[-period:]) / atr_last if atr_last != 0 else 0
    adx_last = calculate_adx(candles, period)

    return {
        "adx": adx_last,
        "plus_di": float(plus_di_last),
        "minus_di": float(minus_di_last),
    }
