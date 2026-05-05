"""
calculator.py — Utilitaires de calcul pour le bot.

Fournit des fonctions de calcul pour les lots, les points,
les niveaux de Fibonacci, et les métriques dérivées.
"""


def calculate_lot_size(risk_eur: float, sl_points: float, point_value: float) -> float:
    """Calcule la taille du lot en fonction du risque et du stop.

    Lot = risk_eur / (sl_points * point_value)

    Args:
        risk_eur: Montant a risquer en euros.
        sl_points: Distance du stop loss en points.
        point_value: Valeur d'un point pour l'actif.

    Returns:
        Taille du lot arrondie a 2 decimales.
    """
    if sl_points <= 0 or point_value <= 0:
        return 0.0

    raw_lot = risk_eur / (sl_points * point_value)
    return round(raw_lot, 2)


def points_to_price(points: float, symbol: str) -> float:
    """Convertit des points en unité de prix selon l'actif.

    La conversion dépend du type d'actif :
    - Forex : 1 pip = 0.0001 (ou 0.01 pour JPY)
    - Indices : 1 point = 0.01 pour US100, 0.1 pour US500, 1.0 pour US30
    - Métaux : 1 point = 0.01 pour XAUUSD, 0.001 pour XAGUSD

    Args:
        points: Nombre de points à convertir.
        symbol: Nom standard de l'actif.

    Returns:
        Valeur en prix.
    """
    conversion_map = {
        "EURUSD": 0.0001,
        "GBPUSD": 0.0001,
        "XAUUSD": 0.01,
        "XAGUSD": 0.001,
        "US100": 0.01,
        "US500": 0.1,
        "US30": 1.0,
    }

    multiplier = conversion_map.get(symbol, 0.0001)
    return points * multiplier


def calculate_fibonacci_levels(high: float, low: float) -> dict:
    """Calcule les niveaux de Fibonacci entre deux extrêmes.

    Les niveaux de retracement standard sont :
    0.0%, 23.6%, 38.2%, 50.0%, 61.8%, 78.6%, 100.0%

    Args:
        high: Point haut du mouvement.
        low: Point bas du mouvement.

    Returns:
        Dict avec les niveaux de Fibonacci (clé = ratio, valeur = prix).
    """
    if high == low:
        return {str(k): high for k in [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]}

    diff = high - low
    levels = {
        "0.0": high,
        "0.236": high - diff * 0.236,
        "0.382": high - diff * 0.382,
        "0.5": high - diff * 0.5,
        "0.618": high - diff * 0.618,
        "0.786": high - diff * 0.786,
        "1.0": low,
    }
    return levels


def calculate_pip_value(symbol: str, lot_size: float = 1.0) -> float:
    """Calcule la valeur d'un pip pour un actif et une taille de lot donnés.

    Args:
        symbol: Nom standard de l'actif.
        lot_size: Taille du lot (défaut: 1.0).

    Returns:
        Valeur d'un pip en devise du compte.
    """
    pip_values = {
        "EURUSD": 10.0,
        "GBPUSD": 10.0,
        "XAUUSD": 10.0,
        "XAGUSD": 50.0,
        "US100": 2.0,
        "US500": 5.0,
        "US30": 1.0,
    }

    base_value = pip_values.get(symbol, 10.0)
    return base_value * lot_size


def normalize_price(price: float, symbol: str) -> float:
    """Arrondit un prix au nombre de décimales standard pour l'actif.

    Args:
        price: Prix à normaliser.
        symbol: Nom standard de l'actif.

    Returns:
        Prix arrondi.
    """
    decimals = {
        "EURUSD": 5,
        "GBPUSD": 5,
        "XAUUSD": 2,
        "XAGUSD": 3,
        "US100": 2,
        "US500": 2,
        "US30": 1,
    }

    ndigits = decimals.get(symbol, 5)
    return round(price, ndigits)
