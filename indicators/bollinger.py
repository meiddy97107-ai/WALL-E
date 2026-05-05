"""
bollinger.py — Calcul des Bandes de Bollinger.

Utilisé principalement pour les métaux (XAUUSD, XAGUSD) dans le contexte
"bollinger" afin de détecter les zones de surachat/survente et
les expansions de volatilité.
"""

import pandas as pd
import numpy as np


def calculate_bollinger(
    candles: pd.DataFrame, period: int = 20, std_dev: float = 2.0
) -> dict:
    """Calcule les Bandes de Bollinger.

    Les Bandes de Bollinger sont composées de :
    - Bande supérieure : SMA + (K × écart-type)
    - Bande médiane : SMA (moyenne mobile simple)
    - Bande inférieure : SMA - (K × écart-type)
    - Bandwidth : largeur relative des bandes (volatilité normalisée)

    Args:
        candles: DataFrame avec colonne "close".
        period: Période de la SMA (défaut: 20).
        std_dev: Nombre d'écarts-types (défaut: 2.0).

    Returns:
        Dict avec upper, middle, lower, bandwidth.
        Retourne des valeurs à 0 si données insuffisantes.
    """
    if candles.empty or len(candles) < period:
        return {"upper": 0.0, "middle": 0.0, "lower": 0.0, "bandwidth": 0.0}

    close = candles["close"]

    # SMA et écart-type
    sma = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()

    # Bandes
    upper = sma + (std * std_dev)
    lower = sma - (std * std_dev)

    # Valeurs actuelles
    current_middle = float(sma.iloc[-1])
    current_upper = float(upper.iloc[-1])
    current_lower = float(lower.iloc[-1])

    # Bandwidth : largeur relative des bandes (indicateur de volatilité)
    bandwidth = ((current_upper - current_lower) / current_middle) if current_middle != 0 else 0.0

    return {
        "upper": current_upper,
        "middle": current_middle,
        "lower": current_lower,
        "bandwidth": bandwidth,
    }


def is_bollinger_squeeze(candles: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> bool:
    """Détecte un squeeze (compression) des Bandes de Bollinger.

    Un squeeze se produit quand les bandes se resserrent, ce qui précède
    souvent un fort mouvement directionnel.

    Args:
        candles: DataFrame avec colonne "close".
        period: Période de calcul (défaut: 20).
        std_dev: Nombre d'écarts-types (défaut: 2.0).

    Returns:
        True si les bandes sont en compression.
    """
    bollinger = calculate_bollinger(candles, period, std_dev)
    if bollinger["bandwidth"] == 0:
        return False

    # Un bandwidth < 0.1 est considéré comme un squeeze
    return bollinger["bandwidth"] < 0.1
