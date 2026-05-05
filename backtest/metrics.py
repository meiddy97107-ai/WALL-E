"""
metrics.py — Calcul des metriques de performance pour le backtest.

Calcule toutes les metriques a partir des trades fermes
et de la courbe d'equite.
"""

import numpy as np
from collections import defaultdict

from utils.logger import get_logger

logger = get_logger("backtest_metrics")


class BacktestMetrics:
    """Calcule les metriques de performance."""

def _safe_round(value, ndigits: int = 0) -> float:
    """Arrondit une valeur, retourne 0.0 si None ou invalide."""
    if value is None:
        return 0.0
    try:
        return round(value, ndigits)
    except (TypeError, ValueError):
        return 0.0


class BacktestMetrics:
    """Calcule les metriques de performance."""

    def compute(self, closed_trades: list, equity_curve: list,
                initial_balance: float, daily_snapshots: dict = None) -> dict:
        """Calcule toutes les metriques de performance.

        Args:
            closed_trades: Liste des trades fermes.
            equity_curve: Courbe d'equite [(datetime, equity), ...].
            initial_balance: Solde initial.
            daily_snapshots: Snapshots journaliers {date_str: balance}.

        Returns:
            Dict complet avec toutes les metriques.
        """
        if not closed_trades:
            return {"total_trades": 0, "status": "no_trades"}

        total = len(closed_trades)
        winners = [t for t in closed_trades if t.get("pnl_eur", 0) > 0]
        losers = [t for t in closed_trades if t.get("pnl_eur", 0) <= 0]
        winning_trades = len(winners)
        losing_trades = total - winning_trades

        sum_wins = sum(t.get("pnl_eur", 0) for t in winners)
        sum_losses = abs(sum(t.get("pnl_eur", 0) for t in losers)) if losers else 0

        # Metriques de base
        win_rate = (winning_trades / total * 100) if total > 0 else 0.0
        total_pnl = sum(t.get("pnl_eur", 0) for t in closed_trades)
        total_pnl_pct = (total_pnl / initial_balance * 100) if initial_balance > 0 else 0.0

        avg_win = sum_wins / winning_trades if winning_trades > 0 else 0.0
        avg_loss = sum_losses / losing_trades if losing_trades > 0 else 0.0
        profit_factor = sum_wins / sum_losses if sum_losses > 0 else 0.0
        expectancy = (avg_win * win_rate / 100) - (avg_loss * (100 - win_rate) / 100) if win_rate > 0 else 0.0

        # Max drawdown
        max_dd_eur, max_dd_pct = self._compute_max_drawdown(equity_curve, initial_balance)

        # Max daily drawdown
        max_daily_dd_eur, max_daily_dd_pct = self._compute_max_daily_drawdown(
            closed_trades, daily_snapshots or {}
        )

        # Sharpe ratio
        sharpe = self._compute_sharpe(equity_curve)

        # Calmar ratio
        calmar = (total_pnl_pct / max_dd_pct) if max_dd_pct > 0 else 0.0

        # Metriques PULSE
        shield_exits = sum(1 for t in closed_trades if t.get("exit_reason") == "SL_HIT")
        tracker_exits = sum(1 for t in closed_trades if t.get("exit_reason") == "PULSE_TRACKER")
        rocket_exits = sum(1 for t in closed_trades if t.get("exit_reason") == "PULSE_ROCKET")
        rocket_pct = (rocket_exits / total * 100) if total > 0 else 0.0

        # Metriques The5ers
        daily_limit_hits = sum(
            1 for t in closed_trades
            if t.get("exit_reason") == "DAILY_LIMIT"
        )

        # Frequence des trades
        trades_per_day = self._compute_trades_per_day(closed_trades)
        trades_per_month = self._compute_trades_per_month(closed_trades)

        best_month = max(trades_per_month.values()) if trades_per_month else 0
        worst_month = min(trades_per_month.values()) if trades_per_month else 0

        # Duree moyenne des trades
        durations = []
        for t in closed_trades:
            entry = t.get("entry_time")
            exit_t = t.get("exit_time")
            if entry is not None and exit_t is not None:
                try:
                    dur = (exit_t - entry).total_seconds() / 60
                    if dur >= 0:
                        durations.append(dur)
                except (TypeError, ValueError):
                    pass
        avg_duration = np.mean(durations) if durations else 0

        return {
            # De base
            "total_trades": total,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": _safe_round(win_rate, 1),
            # Profit
            "total_pnl_eur": _safe_round(total_pnl, 2),
            "total_pnl_pct": _safe_round(total_pnl_pct, 1),
            "avg_win_eur": _safe_round(avg_win, 2),
            "avg_loss_eur": _safe_round(avg_loss, 2),
            "profit_factor": _safe_round(profit_factor, 2),
            "expectancy_eur": _safe_round(expectancy, 2),
            # Risque
            "max_drawdown_eur": _safe_round(max_dd_eur, 2),
            "max_drawdown_pct": _safe_round(max_dd_pct, 1),
            "max_daily_dd_eur": _safe_round(max_daily_dd_eur, 2),
            "max_daily_dd_pct": _safe_round(max_daily_dd_pct, 1),
            "sharpe_ratio": _safe_round(sharpe, 2),
            "calmar_ratio": _safe_round(calmar, 2),
            # PULSE
            "shield_exits": shield_exits,
            "tracker_exits": tracker_exits,
            "rocket_exits": rocket_exits,
            "rocket_pct": _safe_round(rocket_pct, 1),
            # The5ers
            "daily_limit_hits": daily_limit_hits,
            # Frequence
            "avg_duration_minutes": _safe_round(avg_duration, 1),
            "best_month_eur": _safe_round(best_month, 2),
            "worst_month_eur": _safe_round(worst_month, 2),
        }

    def _compute_sharpe(self, equity_curve: list, risk_free_rate: float = 0.04) -> float:
        """Sharpe Ratio annualise base sur les rendements journaliers."""
        if len(equity_curve) < 10:
            return 0.0

        equities = [e for _, e in equity_curve]
        if len(equities) < 10:
            return 0.0

        returns = []
        for i in range(1, len(equities)):
            if equities[i - 1] > 0:
                returns.append((equities[i] - equities[i - 1]) / equities[i - 1])

        if len(returns) < 5:
            return 0.0

        avg_return = np.mean(returns)
        std_return = np.std(returns)

        if std_return == 0:
            return 0.0

        # Annualisation: 252 jours de trading
        daily_rf = risk_free_rate / 252
        sharpe = (avg_return - daily_rf) / std_return * np.sqrt(252)
        return float(sharpe)

    def _compute_max_drawdown(self, equity_curve: list, initial_balance: float) -> tuple:
        """Calcule le drawdown maximum peak-to-trough.

        Returns:
            (max_drawdown_eur, max_drawdown_pct).
        """
        if not equity_curve:
            return 0.0, 0.0

        equities = [initial_balance] + [e for _, e in equity_curve]
        peak = equities[0]
        max_dd_eur = 0
        max_dd_pct = 0

        for eq in equities:
            if eq > peak:
                peak = eq
            dd_eur = peak - eq
            dd_pct = dd_eur / peak * 100 if peak > 0 else 0
            if dd_eur > max_dd_eur:
                max_dd_eur = dd_eur
                max_dd_pct = dd_pct

        return max_dd_eur, max_dd_pct

    def _compute_max_daily_drawdown(self, closed_trades: list,
                                      daily_snapshots: dict) -> tuple:
        """Calcule le drawdown journalier maximum.

        Returns:
            (max_daily_dd_eur, max_daily_dd_pct).
        """
        if not daily_snapshots:
            return 0.0, 0.0

        max_dd_eur = 0
        max_dd_pct = 0

        for date_str, snapshot in daily_snapshots.items():
            # PnL total du jour = somme des PnL des trades fermes ce jour
            day_pnl = 0
            for t in closed_trades:
                exit_t = t.get("exit_time")
                if exit_t and hasattr(exit_t, 'strftime'):
                    try:
                        if exit_t.strftime("%Y-%m-%d") == date_str:
                            day_pnl += t.get("pnl_eur", 0)
                    except (ValueError, AttributeError):
                        pass

            if day_pnl < 0 and snapshot > 0:
                dd_eur = abs(day_pnl)
                dd_pct = dd_eur / snapshot * 100
                if dd_pct > max_dd_pct:
                    max_dd_eur = dd_eur
                    max_dd_pct = dd_pct

        return max_dd_eur, max_dd_pct

    def _compute_trades_per_day(self, closed_trades: list) -> dict:
        """Calcule le nombre de trades par jour."""
        days = defaultdict(int)
        for t in closed_trades:
            exit_t = t.get("exit_time")
            if exit_t and hasattr(exit_t, 'strftime'):
                try:
                    days[exit_t.strftime("%Y-%m-%d")] += 1
                except (ValueError, AttributeError):
                    pass
        return dict(days)

    def _compute_trades_per_month(self, closed_trades: list) -> dict:
        """Calcule le nombre de trades par mois."""
        months = defaultdict(int)
        for t in closed_trades:
            exit_t = t.get("exit_time")
            if exit_t and hasattr(exit_t, 'strftime'):
                try:
                    months[exit_t.strftime("%Y-%m")] += 1
                except (ValueError, AttributeError):
                    pass
        return dict(months)
