"""
report.py — Generation du rapport de performance pour le backtest.

Sauvegarde les resultats dans backtest/results/ :
- Rapport texte (.txt)
- Liste des trades (.csv)
- Courbe d'equite (.csv)
"""

import os
from datetime import datetime
from pathlib import Path

import pandas as pd

from utils.logger import get_logger

logger = get_logger("backtest_report")

RESULTS_DIR = Path(__file__).resolve().parent / "results"


class BacktestReport:
    """Genere le rapport de performance complet."""

    def generate(self, metrics: dict, closed_trades: list,
                 equity_curve: list, strategy: str,
                 asset: str, start: str, end: str, **kwargs) -> None:
        """Cree les fichiers de rapport.

        Args:
            metrics: Dict des metriques calculees.
            closed_trades: Liste des trades fermes.
            equity_curve: Courbe d'equite.
            strategy: Nom de la strategie.
            asset: Nom de l'actif.
            start: Date de debut.
            end: Date de fin.
        """
        RESULTS_DIR.mkdir(exist_ok=True)
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"{strategy}_{asset}_{start}_{end}"

        # 1. Rapport texte
        txt_path = RESULTS_DIR / f"{base_name}.txt"
        self._save_text_report(metrics, strategy, asset, start, end, txt_path)

        # 2. Trades CSV
        trades_path = RESULTS_DIR / f"{base_name}_trades.csv"
        self._save_trades_csv(closed_trades, trades_path)

        # 3. Equite CSV
        equity_path = RESULTS_DIR / f"{base_name}_equity.csv"
        self._save_equity_csv(equity_curve, equity_path)

        logger.info(f"Rapport sauvegarde: {base_name}")

    def print_summary(self, metrics: dict, strategy: str, asset: str) -> None:
        """Affiche un resume dans le terminal."""
        try:
            if not metrics.get("total_trades", 0):
                print(f"\n  [BACKTEST] {strategy.upper()} sur {asset}: aucun trade.")
                return

            win_rate = metrics.get("win_rate", 0) or 0
            profit_factor = metrics.get("profit_factor", 0) or 0
            total_pnl = metrics.get("total_pnl_eur", 0) or 0
            total_pnl_pct = metrics.get("total_pnl_pct", 0) or 0
            max_dd_pct = metrics.get("max_drawdown_pct", 0) or 0
            max_daily_dd = metrics.get("max_daily_dd_pct", 0) or 0
            sharpe = metrics.get("sharpe_ratio", 0) or 0
            shield = metrics.get("shield_exits", 0) or 0
            tracker = metrics.get("tracker_exits", 0) or 0
            rocket = metrics.get("rocket_exits", 0) or 0
            total = metrics.get("total_trades", 1) or 1
            daily_limit_ok = "OK" if (max_daily_dd or 0) < 4 else "DEPASSE"

            print()
            print("=" * 50)
            print(f"  BACKTEST — {strategy.upper()} — {asset}")
            print(f"  Trades total    :  {total}")
            print(f"  Win Rate        :  {win_rate:.1f}%")
            print(f"  Profit Factor   :  {profit_factor:.2f}")
            print(f"  PnL total       :  {total_pnl:+.2f} ({total_pnl_pct:+.1f}%)")
            print(f"  Max Drawdown    :  {max_dd_pct:.1f}%")
            print(f"  Max Daily DD    :  {max_daily_dd:.1f}% [{daily_limit_ok}] (< 4%)")
            print(f"  Sharpe Ratio    :  {sharpe:.2f}")
            print(f"  PULSE Exits     :")
            print(f"    Shield (SL)   :  {shield/total*100:.1f}%" if total > 0 else "    Shield (SL)   : N/A")
            print(f"    Tracker       :  {tracker/total*100:.1f}%" if total > 0 else "    Tracker       : N/A")
            print(f"    Rocket        :  {rocket/total*100:.1f}%" if total > 0 else "    Rocket        : N/A")
            print("=" * 50)
            print()
        except Exception as e:
            print(f"  [BACKTEST] {strategy.upper()} sur {asset}: {len(metrics)} metriques — {e}")

    def _save_text_report(self, metrics: dict, strategy: str,
                          asset: str, start: str, end: str,
                          path: Path) -> None:
        """Sauvegarde le rapport texte."""
        lines = [
            "=" * 55,
            f"  ORB STRUCTURE PRO v2.0 — Backtest Report",
            f"  Strategie: {strategy.upper()}  |  Actif: {asset}",
            f"  Periode: {start} -> {end}",
            "=" * 55,
            "",
            "--- METRIQUES DE BASE ---",
            f"  Trades total       : {metrics.get('total_trades', 0)}",
            f"  Winning trades     : {metrics.get('winning_trades', 0)}",
            f"  Losing trades      : {metrics.get('losing_trades', 0)}",
            f"  Win Rate           : {metrics.get('win_rate', 0):.1f}%",
            "",
            "--- METRIQUES DE PROFIT ---",
            f"  PnL total          : {metrics.get('total_pnl_eur', 0):+.2f}",
            f"  PnL total (%)      : {metrics.get('total_pnl_pct', 0):+.1f}%",
            f"  Avg Win            : {metrics.get('avg_win_eur', 0):.2f}",
            f"  Avg Loss           : {metrics.get('avg_loss_eur', 0):.2f}",
            f"  Profit Factor      : {metrics.get('profit_factor', 0):.2f}",
            f"  Expectancy         : {metrics.get('expectancy_eur', 0):.2f}",
            "",
            "--- METRIQUES DE RISQUE ---",
            f"  Max Drawdown       : {metrics.get('max_drawdown_eur', 0) or 0:.2f} ({(metrics.get('max_drawdown_pct', 0) or 0):.1f}%)",
            f"  Max Daily DD       : {metrics.get('max_daily_dd_eur', 0) or 0:.2f} ({(metrics.get('max_daily_dd_pct', 0) or 0):.1f}%)",
            f"  Sharpe Ratio       : {metrics.get('sharpe_ratio', 0) or 0:.2f}",
            f"  Calmar Ratio       : {metrics.get('calmar_ratio', 0) or 0:.2f}",
            "",
            "--- METRIQUES PULSE ---",
            f"  Shield (SL)        : {metrics.get('shield_exits', 0)}",
            f"  Tracker            : {metrics.get('tracker_exits', 0)}",
            f"  Rocket             : {metrics.get('rocket_exits', 0) or 0} ({(metrics.get('rocket_pct', 0) or 0):.1f}%)",
            "",
            "--- METRIQUES THE5ERS ---",
            f"  Max Daily DD (%)   : {metrics.get('max_daily_dd_pct', 0):.1f}%",
            f"  Daily Limit Hits   : {metrics.get('daily_limit_hits', 0)}",
            "",
            "--- FREQUENCE ---",
            f"  Avg Duration (min) : {metrics.get('avg_duration_minutes', 0):.1f}",
            f"  Best Month         : {metrics.get('best_month_eur', 0):.2f}",
            f"  Worst Month        : {metrics.get('worst_month_eur', 0):.2f}",
            "",
            "=" * 55,
        ]
        path.write_text("\n".join(lines), encoding="utf-8")

    def _save_trades_csv(self, closed_trades: list, path: Path) -> None:
        """Sauvegarde la liste des trades en CSV."""
        rows = []
        for t in closed_trades:
            rows.append({
                "date_open": t.get("entry_time"),
                "date_close": t.get("exit_time"),
                "asset": t.get("asset"),
                "direction": t.get("direction"),
                "entry": t.get("entry_price"),
                "sl": t.get("sl_price"),
                "exit": t.get("exit_price"),
                "pnl_eur": t.get("pnl_eur"),
                "pnl_points": t.get("pnl_points"),
                "exit_reason": t.get("exit_reason"),
                "strategie": t.get("strategie"),
                "conviction": t.get("conviction"),
                "lot_size": t.get("lot_size"),
            })
        df = pd.DataFrame(rows)
        df.to_csv(path, index=False, encoding="utf-8")

    def _save_equity_csv(self, equity_curve: list, path: Path) -> None:
        """Sauvegarde la courbe d'equite en CSV."""
        rows = [{"timestamp": ts, "equity": eq} for ts, eq in equity_curve]
        df = pd.DataFrame(rows)
        df.to_csv(path, index=False, encoding="utf-8")
