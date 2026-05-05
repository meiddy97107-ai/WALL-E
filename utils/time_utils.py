"""
time_utils.py — Gestion des sessions horaires et du temps.

Fournit des utilitaires pour travailler avec les fuseaux horaires,
les sessions de trading, et les horaires du marché.
"""

from datetime import datetime, timedelta
import pytz


# ──────────────────────────────────────────────
# FUSEAUX HORAIRES
# ──────────────────────────────────────────────

PARIS_TZ = pytz.timezone("Europe/Paris")
UTC_TZ = pytz.UTC

# Mapping des timeframes en minutes
TIMEFRAME_MINUTES = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}


def get_current_paris_time() -> datetime:
    """Retourne l'heure actuelle à Paris (CET/CEST selon la saison).

    Returns:
        Datetime avec fuseau horaire Europe/Paris.
    """
    return datetime.now(PARIS_TZ)


def get_current_utc_time() -> datetime:
    """Retourne l'heure actuelle en UTC.

    Returns:
        Datetime avec fuseau horaire UTC.
    """
    return datetime.now(UTC_TZ)


def is_time_between(start: str, end: str, tz=None, now: datetime = None) -> bool:
    """Vérifie si l'heure actuelle est entre deux horaires.

    Les horaires sont au format "HH:MM". Gère le passage minuit
    (ex: "21:00" à "02:00").

    Args:
        start: Heure de début au format "HH:MM".
        end: Heure de fin au format "HH:MM".
        tz: Fuseau horaire. Si None, utilise Paris.

    Returns:
        True si l'heure actuelle est dans la plage.
    """
    if now is None:
        if tz is None:
            now = get_current_paris_time()
        else:
            now = datetime.now(tz)

    now_minutes = now.hour * 60 + now.minute
    start_h, start_m = map(int, start.split(":"))
    end_h, end_m = map(int, end.split(":"))
    start_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m

    if start_minutes <= end_minutes:
        return start_minutes <= now_minutes <= end_minutes
    else:
        return now_minutes >= start_minutes or now_minutes <= end_minutes


def minutes_until(target_time: str, tz=None) -> int:
    """Calcule le nombre de minutes restantes avant une heure cible.

    Args:
        target_time: Heure cible au format "HH:MM".
        tz: Fuseau horaire. Si None, utilise Paris.

    Returns:
        Minutes restantes (peut être négatif si l'heure est passée).
    """
    if tz is None:
        now = get_current_paris_time()
    else:
        now = datetime.now(tz)

    target_h, target_m = map(int, target_time.split(":"))
    target = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)

    if target < now:
        target += timedelta(days=1)

    return int((target - now).total_seconds() / 60)


def is_new_candle(timeframe: str) -> bool:
    """Vérifie si une nouvelle bougie du timeframe donné vient de s'ouvrir.

    Utile pour synchroniser les actions du bot avec les chandeliers.

    Args:
        timeframe: "M1", "M5", "M15", "H1", "H4", "D1".

    Returns:
        True au moment de l'ouverture d'une nouvelle bougie.
    """
    now = datetime.now()
    minutes = now.minute
    hours = now.hour

    if timeframe == "M1":
        return now.second < 2  # Fenêtre de 2 secondes
    elif timeframe == "M5":
        return minutes % 5 == 0 and now.second < 2
    elif timeframe == "M15":
        return minutes % 15 == 0 and now.second < 2
    elif timeframe == "H1":
        return minutes == 0 and now.second < 2
    elif timeframe == "H4":
        return hours % 4 == 0 and minutes == 0 and now.second < 2
    elif timeframe == "D1":
        return hours == 0 and minutes == 0 and now.second < 2
    return False


def is_time(target_time: str, tz=None) -> bool:
    """Verifie si l'heure actuelle correspond exactement a une heure cible (fenetre de 2 sec).

    Args:
        target_time: Heure cible au format "HH:MM".
        tz: Fuseau horaire. Si None, utilise Paris.

    Returns:
        True si l'heure actuelle correspond a la cible.
    """
    if tz is None:
        now = get_current_paris_time()
    else:
        now = datetime.now(tz)

    target_h, target_m = map(int, target_time.split(":"))
    return now.hour == target_h and now.minute == target_m and now.second < 2


def seconds_until_next_m1() -> int:
    """Calcule le nombre de secondes jusqu'a la prochaine bougie M1.

    Chaque bougie M1 commence a :00 secondes de chaque minute.
    Ajoute un buffer de 2 secondes pour s'assurer que la bougie est bien fermee.

    Returns:
        Nombre de secondes avant la prochaine bougie M1.
    """
    now = datetime.now()
    seconds_to_next_minute = 60 - now.second
    # Buffer de 2 secondes
    return max(1, seconds_to_next_minute + 2)


def is_in_session(asset_name: str, config: dict) -> bool:
    """Vérifie si l'heure actuelle est dans la session de trading d'un actif.

    Args:
        asset_name: Nom standard de l'actif (non utilisé, sert de clé).
        config: Configuration de l'actif contenant session_start et session_end.

    Returns:
        True si dans la session de trading.
    """
    session_start = config.get("session_start")
    session_end = config.get("session_end")

    if not session_start or not session_end:
        return True  # Pas de session définie = toujours tradable

    return is_time_between(session_start, session_end)
