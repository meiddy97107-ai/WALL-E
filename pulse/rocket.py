"""
rocket.py — Etat 3 du PULSE : capture du grand mouvement institutionnel.

Etat active quand une expansion de volatilite est detectee.
Stop desserre (filtre ATR x 1.3) pour absorber les meches.
Sortie uniquement sur signal inverse COMPLET de la machine M1.
Aucun nouveau signal sur cet actif pendant ROCKET.
"""

from utils.logger import get_logger
from strategies.structure_trap import StructureTrap

logger = get_logger("pulse_rocket")

ATR_FILTER_ROCKET = 1.3  # Plus tolerant que le filtre standard


class Rocket:
    """Etat 3 : capture du grand mouvement institutionnel.

    Stop desserre pour laisser le mouvement se developper.
    Aucun nouveau trade sur cet actif tant que ROCKET est actif.
    """

    def __init__(self, data_feed=None, structure_trap: StructureTrap = None):
        self._active_rockets = set()
        self._data_feed = data_feed
        self._structure_trap = structure_trap

    def update(self, position: dict, atr_m1: float,
               candles_m1: "pd.DataFrame", config: dict) -> dict:
        """Met a jour une position en etat ROCKET.

        1. Desserre le stop (filtre ATR x 1.3)
        2. Verifie si un signal inverse est apparu
        3. Positionne action: CONTINUE ou EXIT

        Args:
            position: Dict de la position.
            atr_m1: ATR sur M1.
            candles_m1: DataFrame des bougies M1.
            config: Configuration de l'actif.

        Returns:
            Dict de la position mise a jour avec champ "action".
        """
        updated = dict(position)
        updated["compteur_rocket"] = position.get("compteur_rocket", 0) + 1
        updated["action"] = "CONTINUE"

        if atr_m1 <= 0 or candles_m1.empty:
            return updated

        asset = position["actif"]
        self._active_rockets.add(asset)

        # Suivi de structure avec filtre ATR elargi
        self._update_stop(updated, position, atr_m1, candles_m1, config)

        # Detection signal inverse complet
        if self._detect_reversal_signal(position, candles_m1, atr_m1, config):
            logger.info(f"ROCKET: signal inverse detecte -> EXIT ticket={position['ticket']}")
            updated["etat"] = "EXIT"
            updated["action"] = "EXIT"
            self._active_rockets.discard(asset)

        return updated

    def _update_stop(self, updated: dict, position: dict, atr_m1: float,
                     candles_m1: "pd.DataFrame", config: dict) -> None:
        """Suivi de structure avec filtre ATR elargi (plus tolerant)."""
        seuil_rocket = ATR_FILTER_ROCKET * atr_m1
        sl_buffer = config.get("sl_buffer", 0.5) * 0.3  # Buffer plus large en ROCKET

        if position["direction"] == "BUY":
            last_low = self._find_last_valid_low(candles_m1, seuil_rocket)
            if last_low > 0:
                new_sl = last_low - (seuil_rocket * sl_buffer)
                if new_sl > updated.get("sl", 0):
                    updated["sl"] = new_sl
        else:
            last_high = self._find_last_valid_high(candles_m1, seuil_rocket)
            if last_high > 0:
                new_sl = last_high + (seuil_rocket * sl_buffer)
                if new_sl < updated.get("sl", float("inf")):
                    updated["sl"] = new_sl

    # ──────────────────────────────────────────
    # SORTIE : SIGNAL INVERSE COMPLET
    # ──────────────────────────────────────────

    def _detect_reversal_signal(self, position: dict, candles_m1: "pd.DataFrame",
                                atr_m1: float, config: dict) -> bool:
        """Detecte un signal d'entree complet dans le sens inverse.

        Utilise StructureTrap.detect_reversal() si disponible,
        sinon detection basique.
        """
        if len(candles_m1) < 10:
            return False

        asset = position["actif"]
        current_direction = position["direction"]

        # Utiliser StructureTrap si disponible
        if self._structure_trap is not None:
            try:
                return self._structure_trap.detect_reversal(
                    asset, current_direction, candles_m1, atr_m1
                )
            except Exception as e:
                logger.error(f"Erreur detect_reversal pour {asset}: {e}")

        # Fallback via data_feed
        if self._data_feed is not None:
            try:
                trap = StructureTrap(self._data_feed, config)
                return trap.detect_reversal(asset, current_direction, candles_m1, atr_m1)
            except Exception as e:
                logger.error(f"Erreur detect_reversal fallback pour {asset}: {e}")

        # Detection basique
        return self._basic_reversal_detection(position, candles_m1)

    def _basic_reversal_detection(self, position: dict, candles_m1: "pd.DataFrame") -> bool:
        """Detection basique de retournement (fallback)."""
        if len(candles_m1) < 5:
            return False

        if position["direction"] == "BUY":
            closes = candles_m1["close"].values[-5:]
            return all(closes[i] < closes[i - 1] for i in range(1, len(closes)))
        else:
            closes = candles_m1["close"].values[-5:]
            return all(closes[i] > closes[i - 1] for i in range(1, len(closes)))

    # ──────────────────────────────────────────
    # POINTS DE STRUCTURE (filtre elargi)
    # ──────────────────────────────────────────

    def _find_last_valid_low(self, candles: "pd.DataFrame", min_distance: float) -> float:
        if len(candles) < 5:
            return 0.0
        lows = candles["low"].values
        for i in range(len(lows) - 2, 1, -1):
            if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
                if abs(lows[i] - lows[i - 1]) >= min_distance:
                    return lows[i]
        return 0.0

    def _find_last_valid_high(self, candles: "pd.DataFrame", min_distance: float) -> float:
        if len(candles) < 5:
            return 0.0
        highs = candles["high"].values
        for i in range(len(highs) - 2, 1, -1):
            if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
                if abs(highs[i] - highs[i - 1]) >= min_distance:
                    return highs[i]
        return 0.0

    # ──────────────────────────────────────────
    # GESTION DES VERROUS
    # ──────────────────────────────────────────

    def is_asset_locked(self, asset: str) -> bool:
        """Verifie si un actif est verrouille par ROCKET."""
        return asset in self._active_rockets

    def release_asset(self, asset: str) -> None:
        """Libere un actif du verrou ROCKET."""
        self._active_rockets.discard(asset)
        logger.debug(f"Actif {asset} libere du verrou ROCKET.")
