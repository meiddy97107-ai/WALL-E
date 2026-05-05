"""
.py — Mapping des symboles par broker et configuration complète des actifs.

VT Markets utilise des noms de symboles différents du standard.
Le bot convertit automatiquement via SYMBOL_MAP selon le compte actif.
"""

from config.settings import ACTIVE_ACCOUNT

# ──────────────────────────────────────────────
# MAPPING DES SYMBOLES PAR BROKER
# ──────────────────────────────────────────────
SYMBOL_MAP = {
    "EURUSD": {"VT_MARKETS": "EURUSD-VIP", "THE5ERS": "EURUSD"},
    "GBPUSD": {"VT_MARKETS": "GBPUSD-VIP", "THE5ERS": "GBPUSD"},
    "XAUUSD": {"VT_MARKETS": "XAUUSD-VIP", "THE5ERS": "XAUUSD"},
    "XAGUSD": {"VT_MARKETS": "XAGUSD-VIP", "THE5ERS": "XAGUSD"},
    "US500":  {"VT_MARKETS": "SP500.",      "THE5ERS": "US500"},
    "US100":  {"VT_MARKETS": "NAS100.",     "THE5ERS": "US100"},
    "US30":   {"VT_MARKETS": "DJ30.",       "THE5ERS": "US30"},
}


def get_symbol(asset_name: str, broker: str = None) -> str:
    """Retourne le nom du symbole correct selon le broker actif.

    Args:
        asset_name: Nom standard de l'actif (ex: "EURUSD", "US100").
        broker: Nom du broker. Si None, utilise le compte actif.

    Returns:
        Nom du symbole tel qu'attendu par le broker.
    """
    if broker is None:
        broker = ACTIVE_ACCOUNT
    return SYMBOL_MAP[asset_name][broker]


def get_all_symbols(broker: str = None) -> list:
    """Retourne la liste de tous les symboles actifs pour ce broker.

    Args:
        broker: Nom du broker. Si None, utilise le compte actif.

    Returns:
        Liste des noms de symboles pour le broker donné.
    """
    if broker is None:
        broker = ACTIVE_ACCOUNT
    return [SYMBOL_MAP[k][broker] for k in SYMBOL_MAP]


def get_standard_name(broker_symbol: str, broker: str = None) -> str:
    """Convertit un nom de symbole broker en nom standard.

    Args:
        broker_symbol: Nom du symbole chez le broker.
        broker: Nom du broker. Si None, utilise le compte actif.

    Returns:
        Nom standard de l'actif.
    """
    if broker is None:
        broker = ACTIVE_ACCOUNT
    for standard, mapping in SYMBOL_MAP.items():
        if mapping[broker] == broker_symbol:
            return standard
    return broker_symbol


# ──────────────────────────────────────────────
#  — CONFIGURATION COMPLÈTE DES ACTIFS
# ──────────────────────────────────────────────
MARKET_CONFIG = {
    "US100": {
        "name": "Nasdaq",
        "groupe": "US_INDICES",
        "session_start": "16:00",
        "session_end": "21:45",
        "orb_start": "15:30",
        "orb_end": "16:00",
        "contexte": "orb",
        "atr_filter": 2.5,
        "ema_rapide": 5,
        "ema_lente": 8,
        "seuil_pente": 2.5,
        "sl_buffer": 1.0,
        "be_threshold": 2.0,
        "rocket_atr_mult": 1.8,
        "rocket_bars": 3,
        "timeout_h2": 20,
        "retest_tolerance": 2.0,
        "smc_session": False,
        "biais_premarket": True,
    },
    "US500": {
        "name": "S&P 500",
        "groupe": "US_INDICES",
        "session_start": "16:00",
        "session_end": "21:45",
        "orb_start": "15:30",
        "orb_end": "16:00",
        "contexte": "orb",
        "atr_filter": 1.5,
        "ema_rapide": 5,
        "ema_lente": 8,
        "seuil_pente": 0.25,
        "sl_buffer": 1.0,
        "be_threshold": 1.5,
        "rocket_atr_mult": 1.8,
        "rocket_bars": 3,
        "timeout_h2": 20,
        "retest_tolerance": 2.0,
        "smc_session": False,
        "biais_premarket": True,
    },
    "US30": {
        "name": "Dow Jones",
        "groupe": "US_INDICES",
        "session_start": "16:00",
        "session_end": "21:45",
        "orb_start": "15:30",
        "orb_end": "16:00",
        "contexte": "orb",
        "atr_filter": 2.0,
        "ema_rapide": 5,
        "ema_lente": 8,
        "seuil_pente": 1.5,
        "sl_buffer": 1.0,
        "be_threshold": 1.8,
        "rocket_atr_mult": 1.8,
        "rocket_bars": 3,
        "timeout_h2": 20,
        "retest_tolerance": 2.0,
        "smc_session": False,
        "biais_premarket": True,
    },
    "XAUUSD": {
        "name": "Or",
        "groupe": "METALS",
        "contexte": "bollinger",
        "atr_filter": 2.0,
        "ema_rapide": 5,
        "ema_lente": 8,
        "seuil_pente": 0.40,
        "sl_buffer": 1.5,
        "be_threshold": 1.5,
        "rocket_atr_mult": 1.8,
        "rocket_bars": 3,
        "timeout_h2": 20,
        "retest_tolerance": 2.0,
        "smc_session": True,
        "smc_cutoff": "11:00",
        "smc_ema_lente": 8,
        "smc_fib_min": 0.382,
        "smc_fib_max": 0.618,
        "smc_sl_buffer": 0.5,
        "smc_adx_min": 20,
        "smc_pente_h1_seuil": 0.30,
    },
    "XAGUSD": {
        "name": "Argent",
        "groupe": "METALS",
        "contexte": "bollinger",
        "atr_filter": 2.5,
        "ema_rapide": 5,
        "ema_lente": 13,
        "seuil_pente": 0.05,
        "sl_buffer": 2.0,
        "be_threshold": 2.0,
        "rocket_atr_mult": 1.8,
        "rocket_bars": 3,
        "timeout_h2": 20,
        "retest_tolerance": 2.0,
        "smc_session": False,
        "biais_conviction": True,
    },
    "EURUSD": {
        "name": "Euro Dollar",
        "groupe": "FOREX",
        "asian_box_start": "02:00",
        "asian_box_end": "08:00",
        "signal_cutoff": "11:30",
        "contexte": "asian_box",
        "box_amplitude_max": 0.8,
        "atr_filter": 1.8,
        "ema_rapide": 5,
        "ema_lente": 8,
        "seuil_pente": 0.00008,
        "sl_buffer": 1.0,
        "be_threshold": 1.5,
        "rocket_atr_mult": 1.8,
        "rocket_bars": 3,
        "magnets": ["PDH", "PDL"],
        "anti_range_minutes": 45,
        "timeout_h2": 20,
        "retest_tolerance": 2.0,
        "smc_session": True,
        "smc_cutoff": "11:30",
        "smc_ema_lente": 8,
        "smc_fib_min": 0.382,
        "smc_fib_max": 0.618,
        "smc_sl_buffer": 0.3,
        "smc_adx_min": 20,
        "smc_pdx_distance_min_pips": 15,
        "smc_pente_h1_seuil": 0.00005,
    },
    "GBPUSD": {
        "name": "Cable",
        "groupe": "FOREX",
        "asian_box_start": "02:00",
        "asian_box_end": "08:00",
        "signal_cutoff": "11:30",
        "contexte": "asian_box",
        "box_amplitude_max": 1.2,
        "atr_filter": 2.0,
        "ema_rapide": 5,
        "ema_lente": 13,
        "seuil_pente": 0.00010,
        "sl_buffer": 1.2,
        "be_threshold": 2.0,
        "rocket_atr_mult": 1.8,
        "rocket_bars": 3,
        "magnets": ["PDH", "PDL", "US_SESSION_HIGH_PREV", "US_SESSION_LOW_PREV"],
        "anti_range_minutes": 45,
        "timeout_h2": 20,
        "retest_tolerance": 2.0,
        "smc_session": True,
        "smc_cutoff": "11:30",
        "smc_ema_lente": 13,
        "smc_fib_min": 0.382,
        "smc_fib_max": 0.618,
        "smc_sl_buffer": 0.5,
        "smc_adx_min": 20,
        "smc_sweep_obligatoire": True,
        "smc_pente_h1_seuil": 0.00007,
    },
}
