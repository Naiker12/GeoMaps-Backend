from datetime import datetime, timezone

def get_utc_now():
    """
    Retorna el datetime actual con timezone awareness en UTC.
    Estándar obligatorio para toda la aplicación.
    """
    return datetime.now(timezone.utc)
