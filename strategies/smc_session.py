"""
smc_session.py — Strategie 2 : SMC SESSION.

Strategie de pullback institutionnel sur la direction London.
Fonctionne en deux temps :
1. A 10h00 : determiner la direction London avec 3 filtres simultanes
2. Entre 10h00 et cutoff : attendre un pullback dans la zone Fibonacci
   et entrer dans le sens de London quand la confirmation M1 arrive

Genere aussi un score de conviction pour les trades STRUCTURE TRAP.
"""

import pandas as pd

from indicators.atr import calculate_atr
from indicators.ema import calculate_ema, get_slope, is_bullish_cross, is_bearish_cross
from indicators.adx import calculate_adx
from indicators.bollinger import calculate_bollinger
from utils.logger import get_logger
from utils.time_utils import get_current_paris_time, is_time_between
from config.market_config import MARKET_CONFIG
from utils.calculator import calculate_fibonacci_levels

logger = get_logger("strategy_smc_session")

# Actifs autorises pour le London Pullback
LONDON_PULLBACK_ASSETS = ["EURUSD", "GBPUSD", "XAUUSD"]

# Actifs avec biais pre-market uniquement (pas de London Pullback)
PRE_MARKET_ASSETS = ["US100", "US500", "US30", "XAGUSD"]


class SMCSession:
    """
    Strategie 2 : SMC SESSION.

    Deux responsabilites :
    1. Generer des signaux d'entree London Pullback (EURUSD, GBPUSD, XAUUSD)
    2. Calculer un score de conviction pour STRUCTURE TRAP (tous les actifs)
    """

    def __init__(self, data_feed):
        self.data_feed = data_feed
        self.london_direction = {}  # Direction London calculee a 10h00 par actif
        self.conviction_cache = {}  # Cache des scores de conviction par actif
        self.smc_traded_today = {}  # Compteur de trades SMC par actif par jour

    # ──────────────────────────────────────────
    # POINT D'ENTREE PRINCIPAL
    # ──────────────────────────────────────────

    def run(self, asset: str) -> dict | None:
        """
        Point d'entree pour les signaux London Pullback.
        Appele chaque bougie M1 entre 10h00 et le cutoff de l'actif.

        Args:
            asset: Nom standard de l'actif.

        Returns:
            Dict signal ou None.
        """
        config = MARKET_CONFIG.get(asset, {})
        if not config.get("smc_session", False):
            return None

        if asset not in LONDON_PULLBACK_ASSETS:
            return None

        # 1. Si heure == 10h00 : determiner la direction London
        now = get_current_paris_time()
        if now.hour == 10 and now.minute == 0 and now.second < 5:
            self._determine_london_direction(asset)

        # 2. Verifier que la direction London est definie
        ld = self.london_direction.get(asset, {})
        direction_london = ld.get("direction", "UNDEFINED")
        if direction_london == "UNDEFINED":
            return None

        # 3. Verifier les filtres anti-bruit
        candles_m15 = self.data_feed.get_candles(asset, "M15", 80)
        if candles_m15.empty:
            return None

        if not self._check_smc_filters(asset, direction_london, candles_m15, config):
            return None

        # 4. Recuperer les donnees
        candles_m1 = self.data_feed.get_candles(asset, "M1", 200)
        if candles_m1.empty:
            return None

        atr_m1 = calculate_atr(candles_m1, 14)
        if atr_m1 <= 0:
            return None

        # 5. Verifier que le prix est dans la zone Fibonacci
        current_price = float(candles_m1["close"].iloc[-1])
        if not self._is_in_pullback_zone(asset, current_price, ld):
            return None

        # 6. Gachette M1 par actif
        signal = self._compute_entry_trigger(asset, direction_london, candles_m1,
                                              atr_m1, ld, config)
        if signal is None:
            return None

        # 7. Incrementer le compteur
        self.smc_traded_today[asset] = self.smc_traded_today.get(asset, 0) + 1

        # 8. Construire le signal final
        result = {
            "asset": asset,
            "direction": signal["direction"],
            "entry": signal["entry"],
            "sl": signal["sl"],
            "atr_m1": atr_m1,
            "scenario": f"SMC_{signal['direction']}",
            "conviction": "HIGH",
            "strategie": "SMC_SESSION",
        }

        logger.info(
            f"SMC SIGNAL {asset} | Direction={signal['direction']} "
            f"Entry={signal['entry']:.5f} SL={signal['sl']:.5f} "
            f"London={direction_london}"
        )

        return result

    # ──────────────────────────────────────────
    # MODULE 1 — DETERMINATION DIRECTION LONDON
    # ──────────────────────────────────────────

    def _determine_london_direction(self, asset: str) -> None:
        """Determine la direction London a 10h00 avec 3 filtres.

        Les 3 filtres doivent tous confirmer la meme direction.
        Si un seul diverge -> direction = "UNDEFINED".
        """
        config = MARKET_CONFIG.get(asset, {})
        if not config:
            return

        # Recuperer les bougies M15 entre 08h00 et 10h00
        candles_m15 = self.data_feed.get_candles(asset, "M15", 30)
        candles_h1 = self.data_feed.get_candles(asset, "H1", 50)

        if candles_m15.empty or candles_h1.empty:
            logger.warning(f"{asset}: donnees insuffisantes pour direction London")
            return

        # FILTRE 1 — Structure des prix
        candles_m15["time_str"] = candles_m15["time"].dt.strftime("%H:%M")
        london_candles = candles_m15[
            (candles_m15["time_str"] >= "08:00") &
            (candles_m15["time_str"] <= "10:00")
        ]

        if london_candles.empty:
            logger.warning(f"{asset}: aucune bougie entre 08h00 et 10h00")
            return

        london_high = float(london_candles["high"].max())
        london_low = float(london_candles["low"].min())
        london_mid = (london_high + london_low) / 2.0
        prix_10h = float(london_candles["close"].iloc[-1])

        structure_bull = prix_10h > london_mid
        structure_bear = prix_10h < london_mid

        # FILTRE 2 — Expansion ATR H1
        atr_h1_series = pd.Series(dtype=float)
        atr_values = []
        for i in range(len(candles_h1)):
            subset = candles_h1.iloc[:i+1]
            if len(subset) >= 10:
                atr_values.append(calculate_atr(subset, 10))

        atr_h1_at_8h = atr_values[len(atr_values) // 3] if len(atr_values) > 2 else 0
        atr_h1_at_10h = atr_values[-1] if atr_values else 0

        expansion = (atr_h1_at_10h / atr_h1_at_8h) if atr_h1_at_8h > 0 else 0
        atr_valide = expansion >= 1.3

        # FILTRE 3 — Pente EMA 21 sur H1
        ema21_h1 = calculate_ema(candles_h1, 21)
        pente = get_slope(ema21_h1, 5) if not ema21_h1.empty else 0.0
        seuil_pente = config.get("smc_pente_h1_seuil", 0.0)

        pente_bull = pente > seuil_pente
        pente_bear = pente < -seuil_pente

        # DECISION FINALE
        if structure_bull and atr_valide and pente_bull:
            self.london_direction[asset] = {
                "direction": "BULLISH",
                "london_high": london_high,
                "london_low": london_low,
                "london_mid": london_mid,
            }
            logger.info(
                f"{asset} London: BULLISH | "
                f"Structure={prix_10h:.5f}>{london_mid:.5f} | "
                f"ATR_expansion={expansion:.2f} | "
                f"Pente_EMA21={pente:.6f}"
            )
        elif structure_bear and atr_valide and pente_bear:
            self.london_direction[asset] = {
                "direction": "BEARISH",
                "london_high": london_high,
                "london_low": london_low,
                "london_mid": london_mid,
            }
            logger.info(
                f"{asset} London: BEARISH | "
                f"Structure={prix_10h:.5f}<{london_mid:.5f} | "
                f"ATR_expansion={expansion:.2f} | "
                f"Pente_EMA21={pente:.6f}"
            )
        else:
            self.london_direction[asset] = {"direction": "UNDEFINED"}
            logger.info(
                f"{asset} London: UNDEFINED | "
                f"Structure_bull={structure_bull} bear={structure_bear} | "
                f"ATR_expansion={expansion:.2f} (valide={atr_valide}) | "
                f"Pente={pente:.6f} (bull={pente_bull} bear={pente_bear})"
            )

    # ──────────────────────────────────────────
    # MODULE 2 — ZONE DE PULLBACK FIBONACCI
    # ──────────────────────────────────────────

    def _is_in_pullback_zone(self, asset: str, current_price: float,
                              ld: dict) -> bool:
        """Verifie que le prix est dans la zone de pullback Fibonacci valide.

        Zone valide : entre 38.2% et 61.8% du move London.
        """
        direction = ld.get("direction")
        london_high = ld.get("london_high", 0)
        london_low = ld.get("london_low", 0)

        if direction is None or london_high == london_low:
            return False

        london_move = abs(london_high - london_low)

        if direction == "BULLISH":
            fib_382 = london_high - london_move * 0.382
            fib_618 = london_high - london_move * 0.618

            if current_price < fib_618:
                logger.debug(f"{asset} Pullback trop profond: {current_price:.5f} < fib_618={fib_618:.5f}")
                return False

            in_zone = fib_618 <= current_price <= fib_382

        elif direction == "BEARISH":
            fib_382 = london_low + london_move * 0.382
            fib_618 = london_low + london_move * 0.618

            if current_price > fib_618:
                logger.debug(f"{asset} Pullback trop profond: {current_price:.5f} > fib_618={fib_618:.5f}")
                return False

            in_zone = fib_382 <= current_price <= fib_618
        else:
            return False

        if in_zone:
            logger.debug(f"{asset} Pullback dans zone Fib: {current_price:.5f} "
                         f"[{fib_382:.5f} - {fib_618:.5f}]")

        return in_zone

    def _compute_fibonacci_levels(self, london_high: float,
                                  london_low: float) -> dict:
        """Retourne tous les niveaux Fibonacci du move London."""
        return calculate_fibonacci_levels(london_high, london_low)

    # ──────────────────────────────────────────
    # MODULE 3 — FILTRES ANTI-BRUIT SMC
    # ──────────────────────────────────────────

    def _check_smc_filters(self, asset: str, direction: str,
                           candles_m15: pd.DataFrame,
                           config: dict) -> bool:
        """Verifie tous les filtres avant d'autoriser un signal SMC.

        Args:
            asset: Nom de l'actif.
            direction: Direction London ("BULLISH" ou "BEARISH").
            candles_m15: DataFrame M15.
            config: Configuration de l'actif.

        Returns:
            True si tous les filtres passent.
        """
        # FILTRE 1 — ADX M15 > seuil minimum
        adx_min = config.get("smc_adx_min", 20)
        adx = calculate_adx(candles_m15, 14)
        if adx < adx_min:
            logger.debug(f"SMC_BLOQUE_ADX {asset}: ADX={adx:.1f} < {adx_min}")
            return False

        # FILTRE 2 — Un seul trade SMC par actif par jour
        if self.smc_traded_today.get(asset, 0) >= 1:
            logger.debug(f"SMC_BLOQUE_DEJA_TRADE {asset}: deja trade aujourd'hui")
            return False

        # FILTRE 3 — Fenetre horaire respectee
        cutoff = config.get("smc_cutoff", "11:30")
        if not is_time_between("10:00", cutoff):
            logger.debug(f"SMC_BLOQUE_HORAIRE {asset}: hors fenetre (cutoff={cutoff})")
            return False

        # FILTRE 4 — Pas de signal en periode de news
        from filters.news_filter import NewsFilter
        nf = NewsFilter()
        if nf.is_blocked(asset):
            logger.debug(f"SMC_BLOQUE_NEWS {asset}")
            return False

        # FILTRE 5 — GBPUSD uniquement : sweep obligatoire
        if config.get("smc_sweep_obligatoire", False) and asset == "GBPUSD":
            if not self._check_gbpusd_sweep(asset, direction, candles_m15, config):
                return False

        # FILTRE 6 — EURUSD uniquement : distance PDH/PDL
        min_pips = config.get("smc_pdx_distance_min_pips", 0)
        if min_pips > 0 and asset == "EURUSD":
            if not self._check_eurusd_pdl_distance(asset, direction, config, min_pips):
                return False

        return True

    def _check_gbpusd_sweep(self, asset: str, direction: str,
                            candles_m15: pd.DataFrame,
                            config: dict) -> bool:
        """Verifie le sweep obligatoire pour GBPUSD.

        Un sweep = le prix a touche ou depasse un niveau de liquidite
        pendant le pullback AVANT de donner le signal d'entree.

        Niveaux de liquidite :
        - Asian Low (si BULLISH) / Asian High (si BEARISH)
        - PDL / PDH
        - Swing bas/haut M15 recent
        """
        # Verifier les swing points M15 recents
        if len(candles_m15) < 20:
            logger.debug(f"GBPUSD_SMC_BLOQUE_PAS_DE_SWEEP {asset}: pas assez de donnees")
            return False

        recent = candles_m15.tail(20)
        recent_low = float(recent["low"].min())
        recent_high = float(recent["high"].max())
        current_close = float(candles_m15["close"].iloc[-1])

        if direction == "BULLISH":
            # Sweep = un creux a ete forme (liquidite prise en dessous)
            # Verifier si le prix est alle sous un niveau notable
            ld = self.london_direction.get(asset, {})
            london_low = ld.get("london_low", 0)
            if london_low > 0 and recent_low <= london_low:
                logger.debug(f"GBPUSD sweep BULLISH confirme: recent_low={recent_low:.5f} <= london_low={london_low:.5f}")
                return True

            # Sweep d'un swing bas recent
            for i in range(len(recent) - 2, 1, -1):
                if (recent["low"].iloc[i] < recent["low"].iloc[i-1] and
                    recent["low"].iloc[i] < recent["low"].iloc[i+1]):
                    swing_low = float(recent["low"].iloc[i])
                    if current_close > swing_low:
                        logger.debug(f"GBPUSD sweep BULLISH confirme sur swing low={swing_low:.5f}")
                        return True

        elif direction == "BEARISH":
            ld = self.london_direction.get(asset, {})
            london_high = ld.get("london_high", 0)
            if london_high > 0 and recent_high >= london_high:
                logger.debug(f"GBPUSD sweep BEARISH confirme: recent_high={recent_high:.5f} >= london_high={london_high:.5f}")
                return True

            for i in range(len(recent) - 2, 1, -1):
                if (recent["high"].iloc[i] > recent["high"].iloc[i-1] and
                    recent["high"].iloc[i] > recent["high"].iloc[i+1]):
                    swing_high = float(recent["high"].iloc[i])
                    if current_close < swing_high:
                        logger.debug(f"GBPUSD sweep BEARISH confirme sur swing high={swing_high:.5f}")
                        return True

        logger.debug(f"GBPUSD_SMC_BLOQUE_PAS_DE_SWEEP {asset}: aucun sweep detecte")
        return False

    def _check_eurusd_pdl_distance(self, asset: str, direction: str,
                                   config: dict, min_pips: int) -> bool:
        """Verifie la distance minimale au PDH/PDL pour EURUSD.

        Le SL calcule ne doit pas etre dans le PDL (pour BUY) ou PDH (pour SELL).
        """
        candles_d1 = self.data_feed.get_candles(asset, "D1", 5)
        if candles_d1.empty or len(candles_d1) < 2:
            return True

        prev = candles_d1.iloc[-2]
        prev_high = float(prev["high"])
        prev_low = float(prev["low"])

        ld = self.london_direction.get(asset, {})
        london_low = ld.get("london_low", 0)
        london_high = ld.get("london_high", 0)

        # Convertir pips en prix
        from utils.calculator import points_to_price
        min_distance = points_to_price(min_pips, asset)

        if direction == "BULLISH":
            distance_to_pdl = abs(london_low - prev_low) if london_low > 0 else 999
            if distance_to_pdl < min_distance:
                logger.debug(f"EURUSD_SMC_BLOQUE_PDL_TROP_PROCHE: distance={distance_to_pdl:.5f} < {min_distance:.5f}")
                return False
        elif direction == "BEARISH":
            distance_to_pdh = abs(london_high - prev_high) if london_high > 0 else 999
            if distance_to_pdh < min_distance:
                logger.debug(f"EURUSD_SMC_BLOQUE_PDH_TROP_PROCHE: distance={distance_to_pdh:.5f} < {min_distance:.5f}")
                return False

        return True

    # ──────────────────────────────────────────
    # MODULE 4 — GACHETTE M1 PAR ACTIF
    # ──────────────────────────────────────────

    def _compute_entry_trigger(self, asset: str, direction_london: str,
                               candles_m1: pd.DataFrame, atr_m1: float,
                               ld: dict, config: dict) -> dict | None:
        """Verifie les conditions d'entree M1 selon l'actif et la direction London.

        Args:
            asset: Nom de l'actif.
            direction_london: "BULLISH" ou "BEARISH".
            candles_m1: DataFrame M1.
            atr_m1: ATR M1.
            ld: London direction dict (contient london_high, london_low).
            config: Configuration de l'actif.

        Returns:
            Dict signal ou None.
        """
        if direction_london == "BULLISH":
            return self._compute_buy_trigger(asset, candles_m1, atr_m1, ld, config)
        else:
            return self._compute_sell_trigger(asset, candles_m1, atr_m1, ld, config)

    def _compute_buy_trigger(self, asset: str, candles_m1: pd.DataFrame,
                             atr_m1: float, ld: dict, config: dict) -> dict | None:
        """Conditions d'entree BUY selon l'actif."""
        if candles_m1.empty:
            return None

        last_close = float(candles_m1["close"].iloc[-1])
        last_open = float(candles_m1["open"].iloc[-1])
        last_low = float(candles_m1["low"].iloc[-1])
        last_high = float(candles_m1["high"].iloc[-1])

        ema_rapide = calculate_ema(candles_m1, config.get("smc_ema_lente", 8) - 3)  # ~5
        ema_lente = calculate_ema(candles_m1, config.get("smc_ema_lente", 8))
        ema21_h1 = self._get_ema21_h1(asset)

        if ema_rapide.empty or ema_lente.empty:
            return None

        # EMA 21 H1 : contact requis
        if ema21_h1 is not None:
            contact_ema21 = last_low <= ema21_h1 <= last_close
            if not contact_ema21 and last_high < ema21_h1:
                return None

        if asset == "GBPUSD":
            # GBPUSD : entree APRES le sweep
            bougie_verte = last_close > last_open
            cross = is_bullish_cross(ema_rapide, ema_lente)
            if bougie_verte and cross:
                sl = ld.get("london_low", last_low) - atr_m1 * config.get("smc_sl_buffer", 0.5)
                entry = self.data_feed.get_current_price(asset)["ask"]
                logger.debug(f"{asset} SMC BUY (sweep confirme)")
                return {"direction": "BUY", "entry": entry, "sl": sl}

        elif asset == "XAUUSD":
            # XAUUSD : prix reste au-dessus BB milieu M15
            candles_m15 = self.data_feed.get_candles(asset, "M15", 30)
            bb = calculate_bollinger(candles_m15, 20, 2.0) if not candles_m15.empty else {"middle": 0}
            bb_mid = bb.get("middle", 0)

            if bb_mid > 0 and last_close < bb_mid:
                logger.debug(f"{asset} SMC BUY bloque: prix sous BB milieu ({last_close:.2f} < {bb_mid:.2f})")
                return None

            bougie_verte = last_close > last_open
            close_above_ema = last_close > float(ema_lente.iloc[-1])
            cross = is_bullish_cross(ema_rapide, ema_lente)

            if bougie_verte and close_above_ema and cross:
                sl = ld.get("london_low", last_low) - atr_m1 * config.get("smc_sl_buffer", 0.5)
                entry = self.data_feed.get_current_price(asset)["ask"]
                logger.debug(f"{asset} SMC BUY (zone Fib + BB OK)")
                return {"direction": "BUY", "entry": entry, "sl": sl}

        else:
            # EURUSD (defaut)
            bougie_verte = last_close > last_open
            close_above_ema = last_close > float(ema_lente.iloc[-1])
            cross = is_bullish_cross(ema_rapide, ema_lente)

            if bougie_verte and close_above_ema and cross:
                sl = ld.get("london_low", last_low) - atr_m1 * config.get("smc_sl_buffer", 0.5)
                entry = self.data_feed.get_current_price(asset)["ask"]
                logger.debug(f"{asset} SMC BUY (zone Fib + EMA ok)")
                return {"direction": "BUY", "entry": entry, "sl": sl}

        return None

    def _compute_sell_trigger(self, asset: str, candles_m1: pd.DataFrame,
                              atr_m1: float, ld: dict, config: dict) -> dict | None:
        """Conditions d'entree SELL selon l'actif."""
        if candles_m1.empty:
            return None

        last_close = float(candles_m1["close"].iloc[-1])
        last_open = float(candles_m1["open"].iloc[-1])
        last_low = float(candles_m1["low"].iloc[-1])
        last_high = float(candles_m1["high"].iloc[-1])

        ema_rapide = calculate_ema(candles_m1, config.get("smc_ema_lente", 8) - 3)
        ema_lente = calculate_ema(candles_m1, config.get("smc_ema_lente", 8))
        ema21_h1 = self._get_ema21_h1(asset)

        if ema_rapide.empty or ema_lente.empty:
            return None

        if ema21_h1 is not None:
            contact_ema21 = last_high >= ema21_h1 >= last_close
            if not contact_ema21 and last_low > ema21_h1:
                return None

        if asset == "GBPUSD":
            bougie_rouge = last_close < last_open
            cross = is_bearish_cross(ema_rapide, ema_lente)
            if bougie_rouge and cross:
                sl = ld.get("london_high", last_high) + atr_m1 * config.get("smc_sl_buffer", 0.5)
                entry = self.data_feed.get_current_price(asset)["bid"]
                logger.debug(f"{asset} SMC SELL (sweep confirme)")
                return {"direction": "SELL", "entry": entry, "sl": sl}

        elif asset == "XAUUSD":
            candles_m15 = self.data_feed.get_candles(asset, "M15", 30)
            bb = calculate_bollinger(candles_m15, 20, 2.0) if not candles_m15.empty else {"middle": 0}
            bb_mid = bb.get("middle", 0)

            if bb_mid > 0 and last_close > bb_mid:
                logger.debug(f"{asset} SMC SELL bloque: prix au-dessus BB milieu ({last_close:.2f} > {bb_mid:.2f})")
                return None

            bougie_rouge = last_close < last_open
            close_below_ema = last_close < float(ema_lente.iloc[-1])
            cross = is_bearish_cross(ema_rapide, ema_lente)

            if bougie_rouge and close_below_ema and cross:
                sl = ld.get("london_high", last_high) + atr_m1 * config.get("smc_sl_buffer", 0.5)
                entry = self.data_feed.get_current_price(asset)["bid"]
                logger.debug(f"{asset} SMC SELL (zone Fib + BB OK)")
                return {"direction": "SELL", "entry": entry, "sl": sl}

        else:
            bougie_rouge = last_close < last_open
            close_below_ema = last_close < float(ema_lente.iloc[-1])
            cross = is_bearish_cross(ema_rapide, ema_lente)

            if bougie_rouge and close_below_ema and cross:
                sl = ld.get("london_high", last_high) + atr_m1 * config.get("smc_sl_buffer", 0.5)
                entry = self.data_feed.get_current_price(asset)["bid"]
                logger.debug(f"{asset} SMC SELL (zone Fib + EMA ok)")
                return {"direction": "SELL", "entry": entry, "sl": sl}

        return None

    # ──────────────────────────────────────────
    # MODULE 5 — SCORE DE CONVICTION
    # ──────────────────────────────────────────

    def get_conviction(self, asset: str, signal_direction: str) -> str:
        """Calcule le score de conviction pour un signal STRUCTURE TRAP.

        Args:
            asset: Nom standard de l'actif.
            signal_direction: Direction du signal ("BUY" ou "SELL").

        Returns:
            "HIGH" ou "STANDARD".
        """
        config = MARKET_CONFIG.get(asset, {})

        # CAS 3 — London UNDEFINED ou pas de direction
        ld = self.london_direction.get(asset, {})
        direction_london = ld.get("direction", "UNDEFINED")

        # BIAIS PRE-MARKET pour les indices
        if config.get("biais_premarket", False) or asset in PRE_MARKET_ASSETS:
            return self._get_premarket_bias(asset, signal_direction)

        if direction_london == "UNDEFINED":
            return "STANDARD"

        # CAS 1 — NY confirme London (meme direction)
        if (direction_london == "BULLISH" and signal_direction == "BUY") or \
           (direction_london == "BEARISH" and signal_direction == "SELL"):
            logger.debug(f"Conviction {asset}: HIGH (NY confirme London {direction_london})")
            return "HIGH"

        # CAS 2 — London Sweep (direction opposee mais niveau casse)
        if self._has_london_level_broken(asset, direction_london):
            logger.debug(f"Conviction {asset}: HIGH (London Sweep: {direction_london} casse)")
            return "HIGH"

        return "STANDARD"

    def _has_london_level_broken(self, asset: str, direction: str) -> bool:
        """Verifie si le prix a casse un niveau extreme de London.

        Pour detecter un London Sweep :
        direction BULLISH -> a-t-on casse london_low ?
        direction BEARISH -> a-t-on casse london_high ?
        """
        ld = self.london_direction.get(asset, {})
        if ld.get("direction") == "UNDEFINED":
            return False

        london_high = ld.get("london_high", 0)
        london_low = ld.get("london_low", 0)

        # Recuperer le prix actuel
        price_info = self.data_feed.get_current_price(asset)
        current_mid = (price_info["bid"] + price_info["ask"]) / 2

        if direction == "BULLISH":
            return london_low > 0 and current_mid <= london_low
        elif direction == "BEARISH":
            return london_high > 0 and current_mid >= london_high

        return False

    def _get_premarket_bias(self, asset: str, signal_direction: str) -> str:
        """Calcule le biais pre-market pour les indices.

        Biais issu de la direction des futures entre 08h00 et 15h30.
        """
        candles_m15 = self.data_feed.get_candles(asset, "M15", 50)
        if candles_m15.empty:
            return "STANDARD"

        candles_m15["time_str"] = candles_m15["time"].dt.strftime("%H:%M")
        premarket = candles_m15[
            (candles_m15["time_str"] >= "08:00") &
            (candles_m15["time_str"] <= "15:30")
        ]

        if premarket.empty:
            return "STANDARD"

        future_high = float(premarket["high"].max())
        future_low = float(premarket["low"].min())
        future_mid = (future_high + future_low) / 2.0
        prix_15h30 = float(premarket["close"].iloc[-1])

        # Determiner le biais
        if prix_15h30 > future_mid:
            biais = "BULLISH"
        elif prix_15h30 < future_mid:
            biais = "BEARISH"
        else:
            biais = "NEUTRAL"

        if biais == "NEUTRAL":
            return "STANDARD"

        if (biais == "BULLISH" and signal_direction == "BUY") or \
           (biais == "BEARISH" and signal_direction == "SELL"):
            logger.debug(f"Conviction {asset}: HIGH (pre-market {biais} confirme)")
            return "HIGH"

        return "STANDARD"

    # ──────────────────────────────────────────
    # METHODES PRIVEES
    # ──────────────────────────────────────────

    def _get_ema21_h1(self, asset: str) -> float | None:
        """Recupere la valeur EMA 21 sur H1 pour l'actif."""
        candles_h1 = self.data_feed.get_candles(asset, "H1", 30)
        if candles_h1.empty:
            return None
        ema21 = calculate_ema(candles_h1, 21)
        if ema21.empty:
            return None
        return float(ema21.iloc[-1])

    def reset_daily(self) -> None:
        """Appele a 00h00 — remet les compteurs a zero."""
        self.london_direction.clear()
        self.conviction_cache.clear()
        self.smc_traded_today.clear()
        logger.info("SMC SESSION: reset quotidien effectue.")

    def on_new_day(self) -> None:
        """Alias de reset_daily() pour la clarte du code."""
        self.reset_daily()
