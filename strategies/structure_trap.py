"""
structure_trap.py — Stratégie 1 : STRUCTURE TRAP.

Cassure de range (ORB / Bollinger / Asian Box) sur M15 puis entrée M1 au retest
du niveau cassé.
"""

import pandas as pd

from indicators.atr import calculate_atr
from indicators.ema import calculate_ema, get_slope
from indicators.bollinger import calculate_bollinger
from utils.logger import get_logger
from utils.time_utils import is_time_between, get_current_paris_time
from config.market_config import MARKET_CONFIG

logger = get_logger("strategy_structure_trap")

# Constantes de la machine a etats
ETAT_ATTENTE_H1 = "ATTENTE_H1"
ETAT_ATTENTE_L1 = "ATTENTE_L1"
ETAT_ATTENTE_H2 = "ATTENTE_H2"
ETAT_ATTENTE_L2 = "ATTENTE_L2"
ETAT_DECISION = "DECISION"


class StructureTrap:
    """
    Strategie 1 : STRUCTURE TRAP.

    Appelee a chaque bougie M1 pour chaque actif dans sa session.
    Retourne un signal d'entree ou None.
    """

    ARCHIVE = {
        "total": 0,
        "breakout_haut": 0, "breakout_bas": 0,
        "breakout_excursion_confirm": 0,
        "h1_valide": 0, "l1_valide": 0, "h2_valide": 0, "l2_valide": 0,
        "scenario_continue_buy": 0, "scenario_continue_sell": 0,
        "scenario_sweep_buy": 0, "scenario_sweep_sell": 0,
        "ema_triggered": 0,
        "signal_emis": 0,
        "pente_bloque": 0, "pas_en_zone": 0, "ema_cond_non_remplies": 0,
    }

    @staticmethod
    def _init_diag():
        return dict(StructureTrap.ARCHIVE)

    def get_diagnostics(self) -> dict:
        """Retourne les compteurs de diagnostic."""
        return dict(self._diag)

    def __init__(self, data_feed, config: dict = None):
        self.data_feed = data_feed
        self.config = config or {}
        self.state = {}
        self._asian_box_cache = {}
        self._diag = self._init_diag()

    # ──────────────────────────────────────────
    # POINT D'ENTREE PRINCIPAL
    # ──────────────────────────────────────────

    def run(self, asset: str) -> dict | None:
        """
        Point d'entree principal. Appele a chaque bougie M1.

        1. Cooldown
        2. Fenetre horaire
        3. Donnees M1 / M15, ATR M1
        4. COUCHE 1 : Filtre contextuel M15
        5. COUCHE 2 : Machine a etats M1
        6. Entree immediate au marche selon scenario (sans EMA)
        """
        self._diag["total"] += 1

        if self.state.get(asset, {}).get("cooldown_bars", 0) > 0:
            self.state[asset]["cooldown_bars"] -= 1
            return None

        asset_config = MARKET_CONFIG.get(asset, {})
        if not self._is_in_trading_window(asset, asset_config):
            return None

        candles_m1 = self.data_feed.get_candles(asset, "M1", 200)
        candles_m15 = self.data_feed.get_candles(asset, "M15", 50)

        if candles_m1.empty or candles_m15.empty:
            return None

        atr_m1 = calculate_atr(candles_m1, 14)
        if atr_m1 <= 0:
            return None

        context = self._compute_context(asset, candles_m15, asset_config)
        if context is None:
            return None

        breakout_dir = context.get("breakout")
        if breakout_dir is None:
            return None

        if breakout_dir == "HAUT":
            self._diag["breakout_haut"] += 1
        else:
            self._diag["breakout_bas"] += 1

        scenario = self._run_state_machine(asset, breakout_dir, candles_m1, atr_m1, asset_config)
        if scenario is None:
            return None

        if scenario == "CONTINUATION_BUY":
            self._diag["scenario_continue_buy"] += 1
            direction = "BUY"
            entry = self.data_feed.get_current_price(asset)["ask"]
        elif scenario == "CONTINUATION_SELL":
            self._diag["scenario_continue_sell"] += 1
            direction = "SELL"
            entry = self.data_feed.get_current_price(asset)["bid"]
        elif scenario == "SWEEP_BUY":
            self._diag["scenario_sweep_buy"] += 1
            direction = "BUY"
            entry = self.data_feed.get_current_price(asset)["ask"]
        elif scenario == "SWEEP_SELL":
            self._diag["scenario_sweep_sell"] += 1
            direction = "SELL"
            entry = self.data_feed.get_current_price(asset)["bid"]
        else:
            return None

        sm = self.state.get(asset, {})
        sl_buffer = asset_config.get("sl_buffer", 0.5)
        last_low = float(candles_m1["low"].iloc[-1])
        last_high = float(candles_m1["high"].iloc[-1])
        if scenario == "CONTINUATION_BUY":
            sl = sm.get("l1", last_low) - (atr_m1 * sl_buffer)
        elif scenario == "SWEEP_BUY":
            sl = sm.get("l2", last_low) - (atr_m1 * sl_buffer)
        elif scenario == "CONTINUATION_SELL":
            sl = sm.get("h1", last_high) + (atr_m1 * sl_buffer)
        else:
            sl = sm.get("h2", last_high) + (atr_m1 * sl_buffer)

        self._diag["ema_triggered"] += 1
        self._diag["signal_emis"] += 1

        reference_mid = context.get("mid") or context.get("middle", 0.0)

        result = {
            "asset": asset,
            "direction": direction,
            "entry": entry,
            "sl": sl,
            "atr_m1": atr_m1,
            "scenario": scenario,
            "strategie": "STRUCTURE_TRAP",
            "reference_mid": reference_mid,
        }

        logger.info(
            f"SIGNAL {asset} | {scenario} | "
            f"Direction={direction} Entry={entry:.5f} SL={sl:.5f}"
        )

        self._reset_state(asset)
        self.state[asset] = {"cooldown_bars": 30}
        return result

    # ──────────────────────────────────────────
    # COUCHE 2 — MACHINE A ETATS M1 : H1/L1/H2
    # ──────────────────────────────────────────

    def _run_state_machine(self, asset: str, breakout_direction: str,
                           candles_m1: pd.DataFrame, atr_m1: float,
                           config: dict) -> str | None:
        """Detecte la sequence H1 -> L1 -> H2 (ou L1 -> H1 -> L2) sur M1."""
        if asset not in self.state:
            if breakout_direction == "HAUT":
                self.state[asset] = {"etat": ETAT_ATTENTE_H1, "cassure": "HAUT",
                                     "breakout_direction_initiale": "HAUT",
                                     "compteur": 0, "h1": None, "l1": None, "h2": None,
                                     "cooldown_bars": 0}
            else:
                self.state[asset] = {"etat": ETAT_ATTENTE_L1, "cassure": "BAS",
                                     "breakout_direction_initiale": "BAS",
                                     "compteur": 0, "l1": None, "h1": None, "l2": None,
                                     "cooldown_bars": 0}

        sm = self.state[asset]

        if sm.get("breakout_direction_initiale") != breakout_direction:
            self._reset_state(asset)
            return self._run_state_machine(asset, breakout_direction, candles_m1, atr_m1, config)

        sm["compteur"] = sm.get("compteur", 0) + 1

        seuil_retrait = config.get("atr_filter", 1.0) * atr_m1
        timeout_h2 = config.get("timeout_h2", 30)
        if sm["compteur"] > timeout_h2:
            self._reset_state(asset)
            return None

        if sm["cassure"] == "HAUT":
            return self._run_state_machine_buy(asset, sm, candles_m1, seuil_retrait)
        return self._run_state_machine_sell(asset, sm, candles_m1, seuil_retrait)

    def _run_state_machine_buy(self, asset: str, sm: dict,
                               candles_m1: pd.DataFrame, seuil: float) -> str | None:
        etat = sm["etat"]

        if etat == ETAT_ATTENTE_H1:
            h1 = self._get_last_validated_high(candles_m1, seuil)
            if h1 is not None:
                sm["h1"] = h1
                sm["etat"] = ETAT_ATTENTE_L1
                self._diag["h1_valide"] += 1
            return None

        if etat == ETAT_ATTENTE_L1:
            l1 = self._get_last_validated_low(candles_m1, seuil)
            if l1 is not None:
                sm["l1"] = l1
                sm["etat"] = ETAT_ATTENTE_H2
                sm["compteur"] = 0
                self._diag["l1_valide"] += 1
            return None

        if etat == ETAT_ATTENTE_H2:
            h2 = self._get_last_validated_high(candles_m1, seuil)
            if h2 is not None:
                sm["h2"] = h2
                sm["etat"] = ETAT_DECISION
                self._diag["h2_valide"] += 1
            return None

        if etat == ETAT_DECISION:
            if sm["h2"] is None or sm["h1"] is None:
                self._reset_state(asset)
                return None
            if sm["h2"] < sm["h1"]:
                return "SWEEP_SELL"
            if sm["h2"] > sm["h1"]:
                return "CONTINUATION_BUY"
            self._reset_state(asset)
            return None

        return None

    def _run_state_machine_sell(self, asset: str, sm: dict,
                                candles_m1: pd.DataFrame, seuil: float) -> str | None:
        etat = sm["etat"]

        if etat == ETAT_ATTENTE_L1:
            l1 = self._get_last_validated_low(candles_m1, seuil)
            if l1 is not None:
                sm["l1"] = l1
                sm["etat"] = ETAT_ATTENTE_H1
                self._diag["l1_valide"] += 1
            return None

        if etat == ETAT_ATTENTE_H1:
            h1 = self._get_last_validated_high(candles_m1, seuil)
            if h1 is not None:
                sm["h1"] = h1
                sm["etat"] = ETAT_ATTENTE_L2
                sm["compteur"] = 0
                self._diag["h1_valide"] += 1
            return None

        if etat == ETAT_ATTENTE_L2:
            l2 = self._get_last_validated_low(candles_m1, seuil)
            if l2 is not None:
                sm["l2"] = l2
                sm["etat"] = ETAT_DECISION
                self._diag["l2_valide"] += 1
            return None

        if etat == ETAT_DECISION:
            if sm["l2"] is None or sm["l1"] is None:
                self._reset_state(asset)
                return None
            if sm["l2"] > sm["l1"]:
                return "SWEEP_BUY"
            if sm["l2"] < sm["l1"]:
                return "CONTINUATION_SELL"
            self._reset_state(asset)
            return None

        return None

    # ──────────────────────────────────────────
    # COUCHE 1 — FILTRE CONTEXTUEL M15
    # ──────────────────────────────────────────

    def _compute_context(self, asset: str, candles_m15: pd.DataFrame,
                         config: dict) -> dict | None:
        """Dispatche vers le bon contexte selon la config."""
        contexte = config.get("contexte", "")

        if contexte == "orb":
            return self._compute_orb(asset, candles_m15, config)
        elif contexte == "bollinger":
            return self._compute_bollinger_context(asset, candles_m15, config)
        elif contexte == "asian_box":
            return self._compute_asian_box(asset, candles_m15, config)
        else:
            return None

    def _compute_orb(self, asset: str, candles_m15: pd.DataFrame,
                     config: dict) -> dict | None:
        """Calcule l'Opening Range Breakout."""
        if not is_time_between(config.get("session_start", "16:00"),
                               config.get("session_end", "21:45")):
            return None

        orb_start = config.get("orb_start", "15:30")
        orb_end = config.get("orb_end", "16:00")

        candles_m15["time_str"] = candles_m15["time"].dt.strftime("%H:%M")
        orb_candles = candles_m15[
            (candles_m15["time_str"] >= orb_start) &
            (candles_m15["time_str"] <= orb_end)
        ]

        if orb_candles.empty:
            return None

        orb_high = float(orb_candles["high"].max())
        orb_low = float(orb_candles["low"].min())
        orb_mid = (orb_high + orb_low) / 2.0
        amplitude = orb_high - orb_low

        atr_m15 = calculate_atr(candles_m15, 20)
        if atr_m15 <= 0:
            return None

        flag = "VALIDE"
        if amplitude < 0.5 * atr_m15:
            flag = "TROP_ETROIT"
        elif amplitude > 2.5 * atr_m15:
            flag = "NEWS_PROBABLE"

        if flag != "VALIDE":
            logger.debug(f"{asset} ORB: {flag} (amplitude={amplitude:.5f}, atr={atr_m15:.5f})")
            return None

        current_price = float(candles_m15["close"].iloc[-1])
        breakout = None
        if current_price > orb_high:
            breakout = "HAUT"
        elif current_price < orb_low:
            breakout = "BAS"

        if breakout is None:
            return None

        logger.debug(f"{asset} ORB: high={orb_high:.5f} low={orb_low:.5f} breakout={breakout}")
        return {
            "high": orb_high,
            "low": orb_low,
            "mid": orb_mid,
            "flag": flag,
            "breakout": breakout,
        }

    def _compute_bollinger_context(self, asset: str, candles_m15: pd.DataFrame,
                                   config: dict) -> dict | None:
        """Detecte une cassure des Bandes de Bollinger sur M15."""
        bb = calculate_bollinger(candles_m15, 20, 2.0)
        if bb["upper"] == 0.0:
            return None

        last_close = float(candles_m15["close"].iloc[-1])
        last_open = float(candles_m15["open"].iloc[-1])

        flag = "OFF"
        breakout = None

        if last_close > bb["upper"] and last_close > last_open:
            flag = "BREAKOUT_HAUT"
            breakout = "HAUT"
        elif last_close < bb["lower"] and last_close < last_open:
            flag = "BREAKOUT_BAS"
            breakout = "BAS"

        if breakout is None:
            return None

        logger.debug(f"{asset} Bollinger: {flag}")
        return {
            "upper": bb["upper"],
            "middle": bb["middle"],
            "lower": bb["lower"],
            "flag": flag,
            "breakout": breakout,
        }

    def _compute_asian_box(self, asset: str, candles_m15: pd.DataFrame,
                           config: dict) -> dict | None:
        """Calcule la boite asiatique."""
        today = get_current_paris_time().strftime("%Y-%m-%d")
        cache = self._asian_box_cache.get(asset, {})

        # Si la box du jour existe deja, la reutiliser directement.
        if cache.get("date") == today and cache.get("high") is not None:
            asian_high = float(cache["high"])
            asian_low = float(cache["low"])
            asian_mid = (asian_high + asian_low) / 2.0

            current_price = float(candles_m15["close"].iloc[-1])
            breakout = None
            if current_price > asian_high:
                breakout = "HAUT"
            elif current_price < asian_low:
                breakout = "BAS"

            if breakout is None:
                return None

            return {
                "high": asian_high,
                "low": asian_low,
                "mid": asian_mid,
                "breakout": breakout,
                "flag": "VALIDE",
            }

        # Pas de cache du jour: la box ne se calcule que dans la fenetre 02:00-08:00.
        box_start = config.get("asian_box_start", "02:00")
        box_end = config.get("asian_box_end", "08:00")
        if not is_time_between(box_start, box_end):
            return None

        cutoff = config.get("signal_cutoff", "11:30")
        if not is_time_between(config.get("asian_box_start", "02:00"), cutoff):
            if not is_time_between(config.get("asian_box_start", "02:00"),
                                   config.get("asian_box_end", "08:00")):
                now = get_current_paris_time()
                cutoff_h, cutoff_m = map(int, cutoff.split(":"))
                if now.hour * 60 + now.minute > cutoff_h * 60 + cutoff_m:
                    return None

        candles_m15["time_str"] = candles_m15["time"].dt.strftime("%H:%M")
        box_candles = candles_m15[
            (candles_m15["time_str"] >= box_start) &
            (candles_m15["time_str"] <= box_end)
        ]

        if box_candles.empty:
            return None

        asian_high = float(box_candles["high"].max())
        asian_low = float(box_candles["low"].min())
        asian_mid = (asian_high + asian_low) / 2.0
        flag = "VALIDE"

        self._asian_box_cache[asset] = {
            "date": today,
            "high": asian_high,
            "low": asian_low,
            "breakout": None,
        }

        pdh, pdl = self._get_previous_day_hl(asset)
        us_high, us_low = None, None
        if asset == "GBPUSD":
            us_high, us_low = self._get_previous_us_session_hl(asset)

        current_price = float(candles_m15["close"].iloc[-1])
        breakout = None
        if current_price > asian_high:
            breakout = "HAUT"
        elif current_price < asian_low:
            breakout = "BAS"

        if breakout is None:
            return None

        logger.debug(
            f"{asset} AsianBox: high={asian_high:.5f} low={asian_low:.5f} breakout={breakout}"
        )
        return {
            "high": asian_high,
            "low": asian_low,
            "mid": asian_mid,
            "pdh": pdh,
            "pdl": pdl,
            "us_high": us_high,
            "us_low": us_low,
            "flag": flag,
            "breakout": breakout,
        }

    # ──────────────────────────────────────────
    # DETECTION DE RETOURNEMENT (pour PULSE Rocket)
    # ──────────────────────────────────────────

    def detect_reversal(self, asset: str, direction: str,
                        candles_m1: pd.DataFrame, atr_m1: float) -> bool:
        """Detecte un signal inverse pour la sortie ROCKET (EMA)."""
        config = MARKET_CONFIG.get(asset, {})
        if not config:
            return False

        ema_rapide = calculate_ema(candles_m1, config.get("ema_rapide", 5))
        ema_lente = calculate_ema(candles_m1, config.get("ema_lente", 8))

        if ema_rapide.empty or ema_lente.empty:
            return False

        pente = get_slope(ema_lente, 5)
        seuil_pente = config.get("seuil_pente", 0.0)
        last_close = float(candles_m1["close"].iloc[-1])
        ema_lente_val = float(ema_lente.iloc[-1])
        ema_rapide_val = float(ema_rapide.iloc[-1])

        if direction == "BUY":
            if last_close < ema_lente_val and ema_rapide_val < ema_lente_val and pente < -seuil_pente:
                logger.debug(f"{asset} detect_reversal: signal SELL detecte pour sortie BUY")
                return True
        else:
            if last_close > ema_lente_val and ema_rapide_val > ema_lente_val and pente > seuil_pente:
                logger.debug(f"{asset} detect_reversal: signal BUY detecte pour sortie SELL")
                return True

        return False

    # ──────────────────────────────────────────
    # METHODES PRIVEES
    # ──────────────────────────────────────────

    def _is_in_trading_window(self, asset: str, config: dict) -> bool:
        """Verifie si l'heure actuelle est dans la fenetre de trading."""
        contexte = config.get("contexte", "")
        if contexte == "orb":
            return is_time_between(config.get("session_start", "16:00"),
                                   config.get("session_end", "21:45"))
        elif contexte == "asian_box":
            cutoff = config.get("signal_cutoff", "11:30")
            box_start = config.get("asian_box_start", "02:00")
            return is_time_between(box_start, cutoff)
        elif contexte == "bollinger":
            return True
        return False

    def _reset_state(self, asset: str) -> None:
        """Supprime l'etat de suivi pour un actif."""
        if asset in self.state:
            del self.state[asset]

    def _get_last_validated_high(self, candles: pd.DataFrame, seuil: float) -> float | None:
        if len(candles) < 5:
            return None

        highs = candles["high"].values
        lows = candles["low"].values
        for i in range(len(highs) - 2, 1, -1):
            if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
                low_after = min(lows[i:])
                if highs[i] - low_after >= seuil:
                    return float(highs[i])
        return None

    def _get_last_validated_low(self, candles: pd.DataFrame, seuil: float) -> float | None:
        if len(candles) < 5:
            return None

        highs = candles["high"].values
        lows = candles["low"].values
        for i in range(len(lows) - 2, 1, -1):
            if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
                high_after = max(highs[i:])
                if high_after - lows[i] >= seuil:
                    return float(lows[i])
        return None

    def _get_previous_day_hl(self, asset: str) -> tuple:
        """Retourne le Plus Haut et Plus Bas de la journee precedente."""
        candles_d1 = self.data_feed.get_candles(asset, "D1", 5)
        if candles_d1.empty or len(candles_d1) < 2:
            return None, None
        prev = candles_d1.iloc[-2]
        return float(prev["high"]), float(prev["low"])

    def _get_previous_us_session_hl(self, asset: str) -> tuple:
        """Retourne le Plus Haut et Plus Bas de la session US precedente."""
        candles_h1 = self.data_feed.get_candles(asset, "H1", 48)
        if candles_h1.empty:
            return None, None

        candles_h1["time_str"] = candles_h1["time"].dt.strftime("%H:%M")
        us_session = candles_h1[
            (candles_h1["time_str"] >= "14:00") &
            (candles_h1["time_str"] <= "22:00")
        ]
        if us_session.empty or len(us_session) < 2:
            prev_day = candles_h1.iloc[:-24].copy() if len(candles_h1) > 24 else candles_h1
            prev_day["time_str"] = prev_day["time"].dt.strftime("%H:%M")
            us_session = prev_day[
                (prev_day["time_str"] >= "14:00") &
                (prev_day["time_str"] <= "22:00")
            ]
            if us_session.empty:
                return None, None

        return float(us_session["high"].max()), float(us_session["low"].min())
