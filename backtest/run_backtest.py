"""
run_backtest.py — Point d'entree CLI du backtest.

Usage:
    python backtest/run_backtest.py --strategy structure_trap --asset XAUUSD --start 2024-05-01 --end 2025-05-01
    python backtest/run_backtest.py --strategy structure_trap --asset ALL --start 2024-05-01 --end 2025-05-01
    python backtest/run_backtest.py --strategy smc_session --asset EURUSD --start 2024-05-01 --end 2025-05-01
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

from backtest.engine import BacktestEngine
from backtest.metrics import BacktestMetrics
from backtest.report import BacktestReport

STRATEGIES_DISPONIBLES = ["structure_trap", "smc_session"]
SMC_LONDON_ASSETS = ["EURUSD", "GBPUSD", "XAUUSD"]


def parse_args():
    parser = argparse.ArgumentParser(
        description="ORB Structure Pro — Backtest Engine"
    )
    parser.add_argument(
        "--strategy", required=True,
        choices=STRATEGIES_DISPONIBLES,
        help="Strategie a backtester"
    )
    parser.add_argument(
        "--asset", required=True,
        help="Actif (ex: XAUUSD, EURUSD) ou ALL pour tous"
    )
    parser.add_argument(
        "--start", required=True,
        help="Date de debut (format: YYYY-MM-DD)"
    )
    parser.add_argument(
        "--end", required=True,
        help="Date de fin (format: YYYY-MM-DD)"
    )
    parser.add_argument(
        "--balance", default=2492.0, type=float,
        help="Solde initial (defaut: 2492)"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Liste des actifs a backtester
    all_assets = ["EURUSD", "GBPUSD", "XAUUSD", "XAGUSD",
                  "US100", "US500", "US30"]

    if args.asset == "ALL":
        assets = all_assets
    else:
        assets = [args.asset]

    # Filtrer pour SMC SESSION
    if args.strategy == "smc_session":
        assets = [a for a in assets if a in SMC_LONDON_ASSETS]
        if not assets:
            print("SMC SESSION ne supporte que EURUSD, GBPUSD, XAUUSD.")
            return

    for asset in assets:
        print()
        print("=" * 55)
        print(f"  Backtest : {args.strategy.upper()} sur {asset}")
        print(f"  Periode  : {args.start} -> {args.end}")
        print(f"  Solde    : {args.balance:.2f}")
        print("=" * 55)
        print()

        engine = BacktestEngine(
            strategy_name=args.strategy,
            asset=asset,
            start=args.start,
            end=args.end,
            initial_balance=args.balance,
        )

        try:
            results = engine.run()
        except Exception as e:
            import traceback
            print(f"  ERREUR: {e}")
            traceback.print_exc()
            continue

        try:
            metrics = BacktestMetrics().compute(
                closed_trades=results["closed_trades"],
                equity_curve=results["equity_curve"],
                initial_balance=results["initial_balance"],
                daily_snapshots=results.get("daily_snapshots", {}),
            )
        except Exception as e:
            import traceback
            print(f"  ERREUR CALCUL METRIQUES: {e}")
            traceback.print_exc()
            metrics = {"total_trades": 0, "status": "error"}

        report = BacktestReport()

        try:
            report.print_summary(metrics, args.strategy, asset)
        except Exception as e:
            import traceback
            print(f"  ERREUR REPORT summary: {e}")
            traceback.print_exc()

        try:
            report.generate(
                metrics=metrics,
                closed_trades=results["closed_trades"],
                equity_curve=results["equity_curve"],
                strategy=args.strategy,
                asset=asset,
                start=args.start,
                end=args.end,
            )
        except Exception as e:
            import traceback
            print(f"  ERREUR REPORT generate: {e}")
            traceback.print_exc()

    print("Backtest termine.")


if __name__ == "__main__":
    main()
