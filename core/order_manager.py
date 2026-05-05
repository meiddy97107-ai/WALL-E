"""
order_manager.py — Placement, modification et clôture des ordres sur MT5.

Chaque position ouverte par le bot utilise un magic number unique (123456)
pour identifier ses propres trades et ne pas toucher aux trades manuels.
"""

import MetaTrader5 as mt5

from config.settings import MODE, MAGIC_NUMBER
from config.market_config import get_symbol
from utils.logger import get_logger

logger = get_logger("order_manager")


class OrderManager:
    """Gère les ordres sur MT5 : ouverture, modification, clôture."""

    def __init__(self):
        self.magic_number = MAGIC_NUMBER

    # ──────────────────────────────────────────
    # OUVERTURE DE POSITION
    # ──────────────────────────────────────────

    def open_position(
        self,
        symbol: str,
        direction: str,
        lot_size: float,
        sl_price: float,
        tp_price: float = None,
        comment: str = "",
        magic: int = None,
    ) -> dict:
        """Ouvre une position sur le marché.

        Args:
            symbol: Nom standard de l'actif (ex: "EURUSD").
            direction: "BUY" ou "SELL".
            lot_size: Taille du lot.
            sl_price: Prix du stop loss.
            tp_price: Prix du take profit (optionnel).
            comment: Commentaire du trade.
            magic: Magic number (utilise MAGIC_NUMBER par défaut).

        Returns:
            Dict avec les infos du trade ouvert, ou dict vide si échec.
        """
        if magic is None:
            magic = self.magic_number

        broker_symbol = get_symbol(symbol)
        order_type = mt5.ORDER_TYPE_BUY if direction.upper() == "BUY" else mt5.ORDER_TYPE_SELL

        # Récupérer le prix actuel
        tick = mt5.symbol_info_tick(broker_symbol)
        if tick is None:
            logger.error(f"Impossible de récupérer le tick pour {symbol}")
            return {}

        price = tick.ask if direction.upper() == "BUY" else tick.bid

        # Préparer la requête
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": broker_symbol,
            "volume": lot_size,
            "type": order_type,
            "price": price,
            "sl": sl_price,
            "tp": tp_price if tp_price else 0.0,
            "deviation": 10,
            "magic": magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        # Mode PAPER : simuler sans envoyer
        if MODE == "PAPER":
            logger.info(
                f"[PAPER] Ouverture simulée: {direction} {lot_size} {symbol} "
                f"@ {price:.5f} SL={sl_price:.5f} TP={tp_price or 'N/A'}"
            )
            return {
                "ticket": 0,
                "symbol": symbol,
                "direction": direction,
                "volume": lot_size,
                "price": price,
                "sl": sl_price,
                "tp": tp_price,
                "comment": comment,
                "magic": magic,
            }

        try:
            result = mt5.order_send(request)
            if result is None:
                logger.error(f"Échec envoi ordre (retour None) pour {symbol}")
                return {}

            if result.retcode != mt5.TRADE_RETCODE_DONE:
                logger.error(
                    f"Échec ouverture position {symbol}: "
                    f"retcode={result.retcode}, comment={result.comment}"
                )
                return {}

            logger.info(
                f"Position ouverte: {direction} {lot_size} {symbol} "
                f"ticket={result.order} @ {price:.5f}"
            )
            return {
                "ticket": result.order,
                "symbol": symbol,
                "direction": direction,
                "volume": lot_size,
                "price": price,
                "sl": sl_price,
                "tp": tp_price,
                "comment": comment,
                "magic": magic,
            }
        except Exception as e:
            logger.error(f"Exception lors de l'ouverture de position {symbol}: {e}")
            return {}

    # ──────────────────────────────────────────
    # MODIFICATION DU STOP LOSS
    # ──────────────────────────────────────────

    def modify_sl(self, ticket: int, new_sl: float) -> bool:
        """Modifie le stop loss d'une position existante.

        Args:
            ticket: Numéro du ticket de la position.
            new_sl: Nouveau prix du stop loss.

        Returns:
            True si la modification a réussi.
        """
        if MODE == "PAPER":
            logger.info(f"[PAPER] SL modifié pour ticket {ticket} → {new_sl:.5f}")
            return True

        try:
            position = mt5.positions_get(ticket=ticket)
            if position is None or len(position) == 0:
                logger.error(f"Position ticket={ticket} introuvable pour modification SL.")
                return False

            pos = position[0]
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "symbol": pos.symbol,
                "position": ticket,
                "sl": new_sl,
                "tp": pos.tp,
                "magic": pos.magic,
            }

            result = mt5.order_send(request)
            if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                logger.error(f"Échec modification SL ticket={ticket}: retcode={result.retcode}")
                return False

            logger.info(f"SL modifié ticket={ticket} → {new_sl:.5f}")
            return True
        except Exception as e:
            logger.error(f"Exception modify_sl ticket={ticket}: {e}")
            return False

    # ──────────────────────────────────────────
    # CLÔTURE DE POSITION
    # ──────────────────────────────────────────

    def close_position(self, ticket: int, reason: str = "") -> bool:
        """Ferme une position spécifique.

        Args:
            ticket: Numéro du ticket de la position.
            reason: Raison de la clôture (pour logging).

        Returns:
            True si la clôture a réussi.
        """
        if MODE == "PAPER":
            logger.info(f"[PAPER] Clôture simulée ticket={ticket} ({reason})")
            return True

        try:
            position = mt5.positions_get(ticket=ticket)
            if position is None or len(position) == 0:
                logger.error(f"Position ticket={ticket} introuvable.")
                return False

            pos = position[0]
            tick = mt5.symbol_info_tick(pos.symbol)
            if tick is None:
                logger.error(f"Impossible de récupérer le tick pour {pos.symbol}")
                return False

            close_price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
            order_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": pos.symbol,
                "volume": pos.volume,
                "type": order_type,
                "position": ticket,
                "price": close_price,
                "deviation": 10,
                "magic": pos.magic,
                "comment": reason,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            result = mt5.order_send(request)
            if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                logger.error(
                    f"Échec clôture ticket={ticket}: retcode={result.retcode}, "
                    f"comment={result.comment}"
                )
                return False

            logger.info(f"Position clôturée ticket={ticket} ({reason})")
            return True
        except Exception as e:
            logger.error(f"Exception close_position ticket={ticket}: {e}")
            return False

    def close_all_positions(self, reason: str = "") -> bool:
        """Ferme toutes les positions ouvertes par le bot.

        Args:
            reason: Raison de la clôture (pour logging).

        Returns:
            True si toutes les positions ont été fermées avec succès.
        """
        positions = self.get_open_positions()
        success = True
        for pos in positions:
            if not self.close_position(pos["ticket"], reason):
                success = False
        return success

    # ──────────────────────────────────────────
    # LECTURE DES POSITIONS
    # ──────────────────────────────────────────

    def get_open_positions(self) -> list:
        """Retourne toutes les positions ouvertes par le bot.

        Returns:
            Liste de dicts avec les infos de chaque position.
        """
        if MODE == "PAPER":
            return []

        try:
            positions = mt5.positions_get()
            if positions is None:
                return []

            result = []
            for pos in positions:
                if pos.magic == self.magic_number:
                    result.append({
                        "ticket": pos.ticket,
                        "symbol": pos.symbol,
                        "direction": "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL",
                        "volume": pos.volume,
                        "price_open": pos.price_open,
                        "sl": pos.sl,
                        "tp": pos.tp,
                        "profit": pos.profit,
                        "comment": pos.comment,
                        "magic": pos.magic,
                        "time": pos.time,
                    })
            return result
        except Exception as e:
            logger.error(f"Erreur get_open_positions: {e}")
            return []

    def get_position(self, ticket: int) -> dict:
        """Retourne les détails d'une position spécifique.

        Args:
            ticket: Numéro du ticket.

        Returns:
            Dict avec les infos de la position, ou dict vide si introuvable.
        """
        positions = self.get_open_positions()
        for pos in positions:
            if pos["ticket"] == ticket:
                return pos
        return {}

    # ──────────────────────────────────────────
    # ORDRES EN ATTENTE
    # ──────────────────────────────────────────

    def cancel_pending_orders(self) -> bool:
        """Annule tous les ordres en attente du bot.

        Returns:
            True si tous les ordres ont été annulés.
        """
        if MODE == "PAPER":
            return True

        try:
            orders = mt5.orders_get()
            if orders is None:
                return True

            success = True
            for order in orders:
                if order.magic == self.magic_number:
                    request = {
                        "action": mt5.TRADE_ACTION_REMOVE,
                        "order": order.ticket,
                    }
                    result = mt5.order_send(request)
                    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                        logger.error(f"Échec annulation ordre {order.ticket}")
                        success = False
                    else:
                        logger.info(f"Ordre en attente annulé: ticket={order.ticket}")
            return success
        except Exception as e:
            logger.error(f"Erreur cancel_pending_orders: {e}")
            return False
