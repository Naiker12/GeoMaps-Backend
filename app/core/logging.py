"""Configuración de logging estructurado para GeoMaps."""

import logging
import sys

_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def setup_logging() -> None:
    """Configura handlers de consola y archivo con formato unificado."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    if root.hasHandlers():
        root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(console)

    file = logging.FileHandler("server_debug.log", encoding="utf-8")
    file.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(file)

    # Silenciar loggers ruidosos
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


logger = logging.getLogger("geomaps")
