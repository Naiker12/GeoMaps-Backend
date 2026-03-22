from datetime import datetime, timedelta
from app.core.utils.datetime import get_utc_now

MONTHS_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

def format_relative_time(delta: timedelta) -> str:
    """Genera representaciones legibles de proximidad temporal (Relative Time)."""
    if delta.days > 0: return f"Hace {delta.days}d"
    if delta.seconds > 3600: return f"Hace {delta.seconds // 3600}h"
    if delta.seconds > 60: return f"Hace {delta.seconds // 60}m"
    return "Ahora"

def parse_ua(ua: str | None) -> str:
    """Parsea de forma básica el User Agent para identificar dispositivos."""
    if not ua: return "Desconocido"
    ua_low = ua.lower()
    if "iphone" in ua_low or "android" in ua_low: return "Celular"
    if "ipad" in ua_low or "tablet" in ua_low: return "Tablet"
    if "chrome" in ua_low: return "Desktop (Chrome)"
    if "firefox" in ua_low: return "Desktop (Firefox)"
    if "safari" in ua_low: return "Desktop (Safari)"
    return "Desktop"

def group_by_day(user_dates: list[datetime], session_dates: list[datetime], days: int) -> dict:
    """Agrupa métricas por intervalos de 24 horas (Escala diaria)."""
    now = get_utc_now()
    labels = [(now - timedelta(days=i)).strftime("%d/%m") for i in range(days - 1, -1, -1)]

    user_counts = {label: 0 for label in labels}
    for d in user_dates:
        lb = d.strftime("%d/%m")
        if lb in user_counts:
            user_counts[lb] += 1
    
    session_counts = {label: 0 for label in labels}
    for d in session_dates:
        lb = d.strftime("%d/%m")
        if lb in session_counts:
            session_counts[lb] += 1

    return {
        "layerGrowth": [{"date": k, "count": v} for k, v in user_counts.items()],
        "datasetActivity": [{"date": k, "points": v} for k, v in session_counts.items()],
    }

def group_by_month(user_dates: list[datetime], session_dates: list[datetime], days: int) -> dict:
    """Agrupa métricas por intervalos mensuales (Escala semestral/anual)."""
    now = get_utc_now()
    num_months = min(12, (days // 30) + (1 if days % 30 > 0 else 0))

    months = []
    for i in range(num_months - 1, -1, -1):
        dt = now - timedelta(days=i * 30)
        months.append({
            "m": dt.month, 
            "y": dt.year, 
            "name": MONTHS_ES[dt.month - 1], 
            "users": 0,
            "sessions": 0
        })

    for d in user_dates:
        for m in months:
            if d.month == m["m"] and d.year == m["y"]:
                m["users"] += 1
    
    for d in session_dates:
        for m in months:
            if d.month == m["m"] and d.year == m["y"]:
                m["sessions"] += 1

    return {
        "layerGrowth": [{"date": m["name"], "count": m["users"]} for m in months],
        "datasetActivity": [{"date": m["name"], "points": m["sessions"]} for m in months], 
    }
