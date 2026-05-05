"""
engine.py — Orchestrateur principal du backtest.

Rejoue le marche bougie par bougie en M1
et appelle la strategie a chaque pas de temps.
Aucune donnee future accessible (anti-look-ahead bias).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime

import pandas as pd
import numpy as np

from config.market_config import MARKET_CONFIG
from core.mt5_connector import MT5Connector
from backtest.data_loader import BacktestDataLoader
from backtest.simulator import BacktestSimulator
from backtest.backtest_data_feed import BacktestDataFeed
from risk.risk_manager import RiskManager
from risk.streak_brake import StreakBrake
from strategies.structure_trap import StructureTrap
from strategies.smc_session import SMCSession
from pulse.pulse_manager import PulseManager
from indicators.atr import calculate_atr
from utils.logger import get_logger

logger = get_logger("backtest_engine")

PROGRESS_INTERVAL = 10000


class BacktestOrderManagerAdapter:
    """Adaptateur OrderManager pour permettre a PulseManager de piloter le simulateur."""

    def __init__(self, simulator: BacktestSimulator):
        self.simulator = simulator
        self._current_time = datetime.now()
        self._current_price = 0.0

    def set_market_context(self, current_time: datetime, current_price: float) -> None:
        self._current_time = current_time
        self._current_price = current_price

    def modify_sl(self, ticket: int, new_sl: float) -> bool:
        for pos in self.simulator.open_positions:
            if pos.get("id") == ticket or pos.get("ticket") == ticket:
                pos["sl_price"] = new_sl
                pos["sl"] = new_sl
                return True
        return False

    def close_position(self, ticket: int, reason: str = "") -> bool:
        closed = self.simulator.close_position(
            ticket,
            self._current_price,
            self._current_time,
            reason or "PULSE_EXIT",
        )
        return closed is not None

    def get_open_positions(self) -> list:
        positions = []
        for p in self.simulator.open_positions:
            positions.append({
                "ticket": p.get("id"),
                "symbol": p.get("asset"),
                "asset": p.get("asset"),
                "direction": p.get("direction"),
                "price": p.get("entry_price"),
                "sl": p.get("sl_price"),
            })
        return positions

    def sync_state(self, ticket: int, state: dict) -> None:
        for pos in self.simulator.open_positions:
            if pos.get("id") == ticket or pos.get("ticket") == ticket:
                pos["etat"] = state.get("etat", pos.get("etat"))
                pos["sl_price"] = state.get("sl", pos.get("sl_price"))
                pos["sl"] = state.get("sl", pos.get("sl"))
                break


class BacktestEngine:
    """Orchestrateur principal du backtest."""

    def __init__(self, strategy_name: str, asset: str,
                 start: str, end: str,
                 initial_balance: float = 2492.0):
        self.strategy_name = strategy_name
        self.asset = asset
        self.start = start
        self.end = end
        self.initial_balance = initial_balance

        self.connector = MT5Connector()
        self.loader = BacktestDataLoader(self.connector)
        self.simulator = BacktestSimulator(initial_balance)
        self.order_adapter = BacktestOrderManagerAdapter(self.simulator)
        self.risk_mgr = RiskManager()
        self.streak_brake = StreakBrake()
        self.backtest_data_feed = BacktestDataFeed()
        self.pulse_mgr = PulseManager(self.backtest_data_feed, self.order_adapter, self.risk_mgr)
        self._traded_day_by_asset = {}

        # Initialiser la strategie avec le BacktestDataFeed
        if strategy_name == "structure_trap":
            self.strategy = StructureTrap(self.backtest_data_feed)
        elif strategy_name == "smc_session":
            self.strategy = SMCSession(self.backtest_data_feed)
        else:
            raise ValueError(f"Strategie inconnue: {strategy_name}")

    def run(self) -> dict:
        """Execute le backtest complet.

        Returns:
            Dict avec closed_trades, equity_curve, daily_snapshots, initial_balance.
        """
        logger.info(f"Demarrage backtest {self.strategy_name} sur {self.asset}")
        logger.info(f"Periode: {self.start} -> {self.end}")

        # 1. Connecter MT5
        if not self.connector.connect():
            raise ConnectionError("Impossible de se connecter a MT5.")

        try:
            # 2. Charger les donnees
            candles_m1 = self._load_data()
            if candles_m1 is None or candles_m1.empty:
                raise ValueError("Aucune donnee chargee.")

            total_candles = len(candles_m1)

            # 3. Initialiser le risk manager
            self.risk_mgr.on_daily_reset(self.initial_balance)
            skip_next = False
            previous_date = None

            # 4. Boucle principale
            for i in range(1, total_candles):
                current_candle = candles_m1.iloc[i]
                current_time = current_candle["time"]
                current_date = current_time.date()
                current_hour = current_time.hour
                current_minute = current_time.minute

                # Mettre a jour le DataFeed avec le temps courant (tous timeframes)
                self.backtest_data_feed.set_time(current_time)
                self.backtest_data_feed.set_current_price(float(current_candle["close"]))
                self.order_adapter.set_market_context(current_time, float(current_candle["close"]))

                # a. Snapshot daily a 00h00 (premiere bougie du jour)
                if previous_date is not None and current_date != previous_date:
                    self.simulator.snapshot_daily(previous_date)
                    self.risk_mgr.on_daily_reset(self.simulator.balance)
                    self.streak_brake.reset()
                    skip_next = False
                previous_date = current_date

                # b. Kill switch a partir de 21h45 (inclus), toute la soiree
                if (current_hour > 21) or (current_hour == 21 and current_minute >= 45):
                    continue

                asset_config = MARKET_CONFIG.get(self.asset, {})
                if asset_config.get("contexte") == "asian_box":
                    cutoff = asset_config.get("signal_cutoff", "11:30")
                    cutoff_h, cutoff_m = map(int, cutoff.split(":"))
                    if current_hour == cutoff_h and current_minute == cutoff_m:
                        # Cutoff = fin de prise de signal uniquement.
                        # Les positions deja ouvertes restent gerees par PULSE/SL.
                        pass

                # c. Daily loss limit
                if self.simulator.check_daily_limit(current_date):
                    continue

                # d. Streak brake
                if self.streak_brake.should_stop_trading():
                    continue
                skip_next = self.streak_brake.should_skip_next_signal()

                # Regle metier asian_box: un seul trade par jour et par actif
                if asset_config.get("contexte") == "asian_box":
                    traded_day = self._traded_day_by_asset.get(self.asset)
                    if traded_day == current_date.isoformat():
                        continue

                # e. Mettre a jour les positions (SL check)
                atr_m1 = calculate_atr(
                    self._get_recent(candles_m1, i, 50), 14
                ) if i >= 15 else 0.001

                # Mise a jour PULSE (Shield -> Tracker -> Rocket)
                self.pulse_mgr.update_all(self.order_adapter.get_open_positions())

                closed = self.simulator.update_positions(
                    current_candle, self.asset, atr_m1
                )
                for trade in closed:
                    self.pulse_mgr.on_position_closed(trade.get("id", 0), reason=trade.get("exit_reason", ""))
                    result = "WIN" if trade.get("pnl_eur", 0) >= 0 else "LOSS"
                    self.streak_brake.on_trade_closed(result)

                # f. Appeler la strategie
                if not skip_next:
                    signal = self._call_strategy(i)
                    if signal is not None:
                        self._execute_signal(signal, current_candle)

                # g. Equite
                if i % 5000 == 0:
                    self.simulator.record_equity(current_time)

                # h. Progression
                if i % PROGRESS_INTERVAL == 0:
                    pct = (i / total_candles) * 100
                    pnl = self.simulator.balance - self.initial_balance
                    trades = len(self.simulator.closed_trades)
                    logger.info(
                        f"[{self.asset}] {i}/{total_candles} | "
                        f"{pct:.1f}% | Trades: {trades} | PnL: {pnl:+.2f}"
                    )

            # Dernier snapshot
            self.simulator.snapshot_daily(previous_date)

            # Fermer les positions restantes AVANT de retourner
            self.simulator.close_all_positions("BACKTEST_END")

        finally:
            self.connector.disconnect()

        try:
            logger.info(
                f"Backtest termine: {len(self.simulator.closed_trades)} trades, "
                f"PnL: {self.simulator.balance - self.initial_balance:+.2f}"
            )

            # Afficher les diagnostics
            if hasattr(self.strategy, 'get_diagnostics'):
                diag = self.strategy.get_diagnostics()
                total = diag["total"]
                logger.info("=" * 55)
                logger.info(f"DIAGNOSTICS STRATEGIE {self.strategy_name.upper()} sur {self.asset}")
                logger.info(f"  Appels strategie (dans fenetre horaire): {total}")
                logger.info(f"")
                logger.info(f"  COUCHE 1 (contexte):")
                logger.info(f"    Breakouts HAUT valides: {diag['breakout_haut']}")
                logger.info(f"    Breakouts BAS valides : {diag['breakout_bas']}")
                if total > 0:
                    logger.info(f"    (% des appels):        {((diag['breakout_haut']+diag['breakout_bas'])/total*100):.1f}%")
                logger.info(f"")
                logger.info(f"  ETAPE 2 (excursion / retest M1):")
                logger.info(f"    Confirmations excursion >= 1 ATR: {diag.get('breakout_excursion_confirm', 0)}")
                logger.info(f"    (Legacy H1/L1/H2/L2): {diag.get('h1_valide', 0)} / {diag.get('l1_valide', 0)} / "
                            f"{diag.get('h2_valide', 0)} / {diag.get('l2_valide', 0)}")
                logger.info(f"    Scenarios CONTINUATION_* (legacy): "
                            f"{diag.get('scenario_continue_buy', 0)} / {diag.get('scenario_continue_sell', 0)}")
                logger.info(f"    Scenarios SWEEP_* (legacy): "
                            f"{diag.get('scenario_sweep_buy', 0)} / {diag.get('scenario_sweep_sell', 0)}")
                logger.info(f"")
                logger.info(f"  ETAPE 3 (retest + signal):")
                logger.info(f"    Retest declenche: {diag.get('ema_triggered', 0)}")
                logger.info(f"    Pente insuffisante (bloque): {diag['pente_bloque']}")
                logger.info(f"")
                logger.info(f"  SIGNAL FINAL: {diag['signal_emis']}")
                logger.info("=" * 55)
        except Exception as e:
            logger.error(f"Erreur post-backtest: {e}")

        return {
            "closed_trades": self.simulator.closed_trades,
            "equity_curve": self.simulator.equity_curve,
            "daily_snapshots": self.simulator.daily_snapshots,
            "initial_balance": self.initial_balance,
        }

    def _load_data(self) -> pd.DataFrame | None:
        """Charge et prepare toutes les donnees pour le backtest.

        Returns:
            DataFrame M1, ou None si echec.
        """
        candles_m1 = self.loader.load(self.asset, self.start, self.end)
        if candles_m1.empty:
            return None

        required = ["time", "open", "high", "low", "close", "spread"]
        missing = [c for c in required if c not in candles_m1.columns]
        if missing:
            logger.error(f"Colonnes manquantes: {missing}")
            logger.error(f"Colonnes disponibles: {list(candles_m1.columns)}")
            raise ValueError(f"Donnees invalides: colonnes {missing} manquantes")

        # Charger les autres timeframes pour le BacktestDataFeed
        all_data = {"M1": candles_m1}
        try:
            multi = self.loader.load_multi_timeframe(self.asset, self.start, self.end)
            all_data.update(multi)
        except Exception as e:
            logger.warning(f"Multi-timeframe partiel: {e}")

        self.backtest_data_feed.set_data(all_data)
        logger.info(f"{self.asset}: {len(candles_m1)} bougies M1 chargees.")
        return candles_m1

    def _call_strategy(self, current_index: int) -> dict | None:
        """Appelle la strategie avec l'anti-look-ahead en place."""
        try:
            return self.strategy.run(self.asset)
        except Exception as e:
            logger.error(f"Erreur strategie pour {self.asset} a l'index {current_index}: {e}")
            return None

    def _execute_signal(self, signal: dict, current_candle: pd.Series) -> None:
        """Execute un signal via le simulateur."""

        FIXED_LOTS = {
            "EURUSD": 0.30,
            "GBPUSD": 0.30,
            "XAUUSD": 0.02,
            "XAGUSD": 0.01,
            "US100":  1.00,
            "US500":  3.00,
            "US30":   1.00,
        }

        lot_size = FIXED_LOTS.get(self.asset, 0.01)
        price_per_point = self._price_per_point(self.asset)
        point_value = self._point_value(self.asset)
        risk = self.risk_mgr.calculate_risk_for_trade(self.simulator.balance)
        sl_distance = (risk * price_per_point) / (lot_size * point_value)

        if signal["direction"] == "BUY":
            sl_price = signal["entry"] - sl_distance
        else:
            sl_price = signal["entry"] + sl_distance

        logger.info(
            f"DEBUG DIRECTION: signal={signal['direction']} "
            f"asset={self.asset} "
            f"entry={signal['entry']:.5f} "
            f"scenario={signal.get('scenario','?')}"
        )

        logger.info(f"EXECUTION signal: {signal['direction']} {self.asset} "
                     f"entry={signal['entry']:.5f} sl={sl_price:.5f} "
                     f"dist={sl_distance:.5f} lot={lot_size:.2f} risk={risk:.2f}")

        # Maximum 1 position ouverte par actif à la fois
        positions_ouvertes = [
            p for p in self.simulator.open_positions
            if p["asset"] == self.asset
        ]
        if len(positions_ouvertes) >= 1:
            logger.debug(f"SIGNAL IGNORE — position déjà ouverte sur {self.asset}")
            return

        opened = self.simulator.open_position(
            asset=self.asset,
            direction=signal["direction"],
            lot_size=lot_size,
            sl_price=sl_price,
            entry_price=signal["entry"],
            risk_eur=risk,
            strategie=self.strategy_name,
            conviction=signal.get("conviction", "STANDARD"),
            entry_time=current_candle["time"],
        )
        if opened:
            self.pulse_mgr.on_position_opened({
                "ticket": opened.get("id"),
                "actif": self.asset,
                "direction": signal["direction"],
                "prix_entree": signal["entry"],
                "sl": sl_price,
                "risk_initial_": risk,
                "conviction": signal.get("conviction", "STANDARD"),
                "strategie": self.strategy_name.upper(),
                "reference_mid": signal.get("reference_mid", 0.0),
            })
            self._traded_day_by_asset[self.asset] = current_candle["time"].date().isoformat()

    def _get_recent(self, df: pd.DataFrame, index: int, n: int) -> pd.DataFrame:
        """Retourne les N dernieres bougies jusqu'a index (exclu)."""
        return df.iloc[max(0, index - n):index].copy()

    def _point_value(self, asset: str) -> float:
        values = {
            "EURUSD": 10.0, "GBPUSD": 10.0,
            "XAUUSD": 10.0, "XAGUSD": 50.0,
            "US100": 2.0, "US500": 5.0, "US30": 1.0,
        }
        return values.get(asset, 10.0)

    def _price_per_point(self, asset: str) -> float:
        mapping = {
            "EURUSD": 0.0001, "GBPUSD": 0.0001,
            "XAUUSD": 0.01, "XAGUSD": 0.001,
            "US100": 0.01, "US500": 0.1, "US30": 1.0,
        }
        return mapping.get(asset, 0.0001)
