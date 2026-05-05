"""
ema.py — Calcul des moyennes mobiles exponentielles (EMA).

Utilisé par les stratégies pour la détection de tendance,
les croisements d'EMA, et le calcul de pente.
"""

import pandas as pd
import numpy as np


def calculate_ema(candles: pd.DataFrame, period: int, column: str = "close") -> pd.Series:
    """Calcule l'EMA (Exponential Moving Average) sur la colonne spécifiée.

    L'EMA donne plus de poids aux valeurs récentes, ce qui la rend
    plus réactive que la SMA aux changements de prix.

    Args:
        candles: DataFrame avec les données de prix.
        period: Période de l'EMA.
        column: Nom de la colonne à utiliser ("close", "open", "high", "low").

    Returns:
        Series pandas avec les valeurs de l'EMA.
    """
    if candles.empty or column not in candles.columns:
        return pd.Series(dtype=float)

    return candles[column].ewm(span=period, adjust=False).mean()


def get_slope(ema_series: pd.Series, n_bars: int = 5) -> float:
    """Calcule la pente de l'EMA sur les N dernières bougies.

    Une pente positive indique une tendance haussière (momentum HAUSSIER).
    Une pente négative indique une tendance baissière (momentum BAISSIER).
    La valeur absolue indique la force du momentum.

    Args:
        ema_series: Series pandas des valeurs EMA.
        n_bars: Nombre de bougies pour le calcul de la pente (défaut: 5).

    Returns:
        Pente de l'EMA (coefficient directeur de la régression linéaire).
    """
    if ema_series.empty or len(ema_series) < n_bars:
        return 0.0

    y = ema_series.iloc[-n_bars:].values
    x = np.arange(n_bars)

    # Régression linéaire : pente = covariance(x, y) / variance(x)
    slope = np.polyfit(x, y, 1)[0]
    return float(slope)


def is_bullish_cross(fast: pd.Series, slow: pd.Series) -> bool:
    """Vérifie si l'EMA rapide vient de croiser au-dessus de l'EMA lente.

    Signal HAUSSIER : la moyenne rapide passe au-dessus de la lente,
    indiquant un changement de momentum vers le haut.

    Args:
        fast: Series de l'EMA rapide.
        slow: Series de l'EMA lente.

    Returns:
        True si croisement haussier vient de se produire.
    """
    if fast.empty or slow.empty or len(fast) < 2 or len(slow) < 2:
        return False

    return fast.iloc[-2] <= slow.iloc[-2] and fast.iloc[-1] > slow.iloc[-1]


def is_bearish_cross(fast: pd.Series, slow: pd.Series) -> bool:
    """Vérifie si l'EMA rapide vient de croiser en dessous de l'EMA lente.

    Signal BAISSIER : la moyenne rapide passe en dessous de la lente,
    indiquant un changement de momentum vers le bas.

    Args:
        fast: Series de l'EMA rapide.
        slow: Series de l'EMA lente.

    Returns:
        True si croisement baissier vient de se produire.
    """
    if fast.empty or slow.empty or len(fast) < 2 or len(slow) < 2:
        return False

    return fast.iloc[-2] >= slow.iloc[-2] and fast.iloc[-1] < slow.iloc[-1]
