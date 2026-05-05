"""
tracker.py — Etat 2 du PULSE : suivi de structure.

La position est en break-even et suit la structure du marche
avec le filtre ATR. Le stop est deplace progressivement.

Actions a chaque bougie M1 :
1. Identifier le dernier creux/sommet valide par ATR
2. Deplacer le stop favorablement
3. Verifier le retournement structurel -> EXIT
4. Verifier expansion ATR -> ROCKET
"""

from utils.logger import get_logger

logger = get_logger("pulse_tracker")

ATR_MOYEN_FENETRE = 20
ROCKET_MULTIPLICATEUR = 1.8
ROCKET_BARS_CONFIRMES = 3


class Tracker:
    """Etat 2 : suivi de structure avec deplacement du stop."""

    def update(self, position: dict, atr_m1: float,
               candles_m1: "pd.DataFrame", config: dict) -> dict:
        """Met a jour une position en etat TRACKER.

        1. Identifie le dernier point de structure valide
        2. Deplace le stop en consequence
        3. Verifie le retournement de structure -> EXIT
        4. Verifie l'expansion ATR -> ROCKET

        Args:
            position: Dict de la position.
            atr_m1: ATR sur M1.
            candles_m1: DataFrame des bougies M1.
            config: Configuration de l'actif.

        Returns:
            Dict de la position mise a jour avec champ "action".
        """
        updated = dict(position)
        updated["action"] = "CONTINUE"

        if candles_m1.empty or atr_m1 <= 0:
            return updated

        atr_filter = config.get("atr_filter", 1.0)
        min_structure_distance = atr_filter * atr_m1

        if position["direction"] == "BUY":
            self._update_buy(position, updated, candles_m1, atr_m1,
                             min_structure_distance, config)
        else:
            self._update_sell(position, updated, candles_m1, atr_m1,
                              min_structure_distance, config)

        # Detection ROCKET
        if self._check_rocket_condition(candles_m1, atr_m1, config, updated):
            updated["etat"] = "ROCKET"
            updated["action"] = "ROCKET"
            logger.info(f"TRACKER -> ROCKET: ticket={position['ticket']}")

        return updated

    def _update_buy(self, position: dict, updated: dict,
                    candles_m1: "pd.DataFrame", atr_m1: float,
                    min_distance: float, config: dict) -> None:
        """Met a jour le SL pour une position BUY."""
        last_low = self._find_last_valid_low(candles_m1, min_distance)
        if last_low > 0:
            new_sl = last_low - (config.get("sl_buffer", 0.5) * atr_m1 * 0.2)
            if new_sl > updated.get("sl", 0):
                updated["sl"] = new_sl

        # Retournement baissier
        if self._detect_structural_reversal("BUY", candles_m1, min_distance):
            logger.info(f"TRACKER: retournement baissier -> EXIT ticket={position['ticket']}")
            updated["etat"] = "EXIT"
            updated["action"] = "EXIT"

    def _update_sell(self, position: dict, updated: dict,
                     candles_m1: "pd.DataFrame", atr_m1: float,
                     min_distance: float, config: dict) -> None:
        """Met a jour le SL pour une position SELL."""
        last_high = self._find_last_valid_high(candles_m1, min_distance)
        if last_high > 0:
            new_sl = last_high + (config.get("sl_buffer", 0.5) * atr_m1 * 0.2)
            if new_sl < updated.get("sl", float("inf")):
                updated["sl"] = new_sl

        # Retournement haussier
        if self._detect_structural_reversal("SELL", candles_m1, min_distance):
            logger.info(f"TRACKER: retournement haussier -> EXIT ticket={position['ticket']}")
            updated["etat"] = "EXIT"
            updated["action"] = "EXIT"

    # ──────────────────────────────────────────
    # DETECTION STRUCTURE
    # ──────────────────────────────────────────

    def _detect_structural_reversal(self, direction: str,
                                    candles: "pd.DataFrame",
                                    seuil: float) -> bool:
        """Detecte un retournement structurel complet (H1/L1/H2).

        BUY  : si H2 < H1 valide par ATR -> retournement baissier
        SELL : si L2 > L1 valide par ATR -> retournement haussier

        Args:
            direction: Direction du trade ("BUY" ou "SELL").
            candles: DataFrame des bougies M1.
            seuil: Seuil de validation ATR.

        Returns:
            True si un retournement structurel complet est detecte.
        """
        if len(candles) < 20:
            return False

        if direction == "BUY":
            h1 = self._find_last_valid_high(candles, seuil)
            if h1 is None or h1 == 0:
                return False
            # Chercher un H2 apres H1
            h1_idx = self._find_high_index(candles, h1)
            if h1_idx is None:
                return False
            sub = candles.iloc[h1_idx:].copy()
            sub = sub.reset_index(drop=True)
            h2 = self._find_last_valid_high(sub, seuil)
            if h2 and h2 > 0 and h2 < h1:
                return True
        else:
            l1 = self._find_last_valid_low(candles, seuil)
            if l1 is None or l1 == 0:
                return False
            l1_idx = self._find_low_index(candles, l1)
            if l1_idx is None:
                return False
            sub = candles.iloc[l1_idx:].copy()
            sub = sub.reset_index(drop=True)
            l2 = self._find_last_valid_low(sub, seuil)
            if l2 and l2 > 0 and l2 > l1:
                return True

        return False

    def _find_high_index(self, candles: "pd.DataFrame", high_value: float) -> int | None:
        """Trouve l'index d'un sommet dans les bougies."""
        highs = candles["high"].values
        for i in range(len(highs) - 1, 1, -1):
            if abs(highs[i] - high_value) < 0.00001:
                return i
        return None

    def _find_low_index(self, candles: "pd.DataFrame", low_value: float) -> int | None:
        """Trouve l'index d'un creux dans les bougies."""
        lows = candles["low"].values
        for i in range(len(lows) - 1, 1, -1):
            if abs(lows[i] - low_value) < 0.00001:
                return i
        return None

    # ──────────────────────────────────────────
    # DETECTION ROCKET
    # ──────────────────────────────────────────

    def _check_rocket_condition(self, candles: "pd.DataFrame", atr_m1: float,
                                config: dict, position: dict) -> bool:
        """Verifie si les conditions de passage en ROCKET sont reunies.

        ATR actuel > ROCKET_MULTIPLICATEUR x ATR moyen sur ATR_MOYEN_FENETRE bougies.
        Doit etre soutenu pendant ROCKET_BARS_CONFIRMES bougies consecutives.
        """
        rocket_mult = config.get("rocket_atr_mult", ROCKET_MULTIPLICATEUR)

        if len(candles) < ATR_MOYEN_FENETRE:
            return False

        from indicators.atr import get_atr_mean
        atr_mean = get_atr_mean(candles, 14, ATR_MOYEN_FENETRE)

        if atr_mean <= 0:
            return False

        if atr_m1 > rocket_mult * atr_mean:
            compteur = position.get("compteur_rocket", 0) + 1
            position["compteur_rocket"] = compteur
            return compteur >= ROCKET_BARS_CONFIRMES

        position["compteur_rocket"] = 0
        return False

    # ──────────────────────────────────────────
    # POINTS DE STRUCTURE
    # ──────────────────────────────────────────

    def _find_last_valid_low(self, candles: "pd.DataFrame", min_distance: float) -> float:
        """Trouve le dernier creux valide avec une distance minimale ATR."""
        if len(candles) < 5:
            return 0.0

        lows = candles["low"].values
        for i in range(len(lows) - 2, 1, -1):
            if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
                prev_low = lows[i - 1]
                if abs(lows[i] - prev_low) >= min_distance:
                    return lows[i]
        return 0.0

    def _find_last_valid_high(self, candles: "pd.DataFrame", min_distance: float) -> float:
        """Trouve le dernier sommet valide avec une distance minimale ATR."""
        if len(candles) < 5:
            return 0.0

        highs = candles["high"].values
        for i in range(len(highs) - 2, 1, -1):
            if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
                prev_high = highs[i - 1]
                if abs(highs[i] - prev_high) >= min_distance:
                    return highs[i]
        return 0.0
