# ORB STRUCTURE PRO v2.0

Bot de trading algorithmique pour MetaTrader 5 (MT5) — Prop Firm The5ers.

Strategies : Structure Trap (indices US) + SMC Session (forex/metaux).

---

## Stack technique

- Python 3.11+
- MetaTrader5 (librairie officielle MT5 Python)
- pandas, numpy
- python-dotenv
- loguru
- schedule
- pytz
- pytest

---

## Installation

### 1. Cloner le projet

```bash
cd orb_structure_pro
```

### 2. Creer un environnement virtuel (recommande)

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
source .venv/bin/activate  # Linux/Mac
```

### 3. Installer les dependances

```bash
pip install -r requirements.txt
```

---

## Configuration

### 1. Copier le fichier .env.example en .env

```bash
copy .env.example .env   # Windows
cp .env.example .env     # Linux/Mac
```

### 2. Remplir le .env

| Variable | Description |
|---|---|
| `ACTIVE_ACCOUNT` | `VT_MARKETS` ou `THE5ERS` |
| `VT_LOGIN` / `VT_PASSWORD` / `VT_SERVER` | Identifiants compte VT Markets |
| `THE5ERS_LOGIN` / `THE5ERS_PASSWORD` / `THE5ERS_SERVER` | Identifiants compte The5ers |
| `MT5_PATH` | Chemin vers terminal64.exe |
| `CHALLENGE_START_BALANCE` | Capital de depart du challenge |
| `MODE` | `LIVE`, `BACKTEST` ou `PAPER` |

### 3. Mode PAPER (test sans risque)

```env
MODE=PAPER
```

En mode PAPER, le bot simule les ordres sans les envoyer a MT5.

---

## Lancement

### Mode LIVE

```bash
python main.py
```

### Mode PAPER

Modifier le .env :

```env
MODE=PAPER
```

Puis lancer :

```bash
python main.py
```

---

## Backtest

Le moteur de backtest utilise les donnees historiques MT5 directement via
la connexion deja etablie. MT5 VT Markets doit etre ouvert et connecte.

### Backtest STRUCTURE TRAP — XAUUSD (recommande)

```bash
python backtest/run_backtest.py --strategy structure_trap --asset XAUUSD --start 2024-05-01 --end 2025-05-01
```

### Backtest STRUCTURE TRAP — tous les actifs

```bash
python backtest/run_backtest.py --strategy structure_trap --asset ALL --start 2024-05-01 --end 2025-05-01
```

### Backtest SMC SESSION — actifs compatibles

```bash
python backtest/run_backtest.py --strategy smc_session --asset ALL --start 2024-05-01 --end 2025-05-01
```

Les resultats sont sauvegardes dans `backtest/results/` :
- Rapport texte (.txt)
- Liste des trades (.csv)
- Courbe d'equite (.csv)

---

## Tests

```bash
pytest
```

---

## Structure du projet

```
orb_structure_pro/
├── .env                          ← Variables d'environnement
├── .env.example                  ← Template vide
├── .gitignore
├── requirements.txt
├── README.md
├── main.py                       ← Point d'entree live
├── config/                       ← Configuration
│   ├── settings.py               ← .env + constantes
│   ├── market_config.py          ← Config des actifs
│   └── phase_config.py           ← Phases de risque
├── core/                         ← Modules MT5
│   ├── mt5_connector.py          ← Connexion MT5
│   ├── data_feed.py              ← Donnees temps reel
│   └── order_manager.py          ← Ordres
├── strategies/                   ← Strategies
│   ├── structure_trap.py         ← Structure Trap (ORB)
│   └── smc_session.py            ← SMC Session (London Pullback)
├── indicators/                   ← Indicateurs techniques
│   ├── atr.py, ema.py, bollinger.py, adx.py
├── risk/                         ← Gestion des risques
│   ├── risk_manager.py, phase_detector.py
│   ├── budget_tracker.py, streak_brake.py
├── pulse/                        ← Systeme PULSE
│   ├── pulse_manager.py, shield.py
│   ├── tracker.py, rocket.py
├── filters/                      ← Filtres de signaux
│   ├── news_filter.py, spread_filter.py
│   ├── anti_chop.py, anti_range.py
├── utils/                        ← Utilitaires
│   ├── logger.py, time_utils.py, calculator.py
├── backtest/                     ← Backtest engine
│   ├── run_backtest.py           ← Point d'entree CLI
│   ├── engine.py                 ← Moteur principal
│   ├── data_loader.py            ← Chargement donnees MT5
│   ├── simulator.py              ← Simulateur d'ordres
│   ├── metrics.py                ← Metriques performance
│   ├── report.py                 ← Generation rapport
│   └── results/                  ← Resultats sauvegardes
└── logs/                         ← Logs journaliers
```

---

## Phases de developpement

- **Phase 1** : Structure du projet, connexion MT5, risque, PULSE, filtres
- **Phase 2** : Implementation strategie STRUCTURE TRAP
- **Phase 3** : Implementation strategie SMC SESSION
- **Phase 4** : Integration finale, boucle principale complete, tests d'integration
- **Phase 5** : Moteur de backtest sur donnees historiques MT5

---

## Avertissement

Le trading algorithmique comporte des risques financiers importants. Ce bot est fourni a titre educatif. Testez-le en mode PAPER avant toute utilisation sur un compte reel. Les performances passees ne garantissent pas les resultats futurs.
