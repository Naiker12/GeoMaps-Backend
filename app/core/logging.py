import logging
import sys
from typing import Any

# Configurar logging estructurado
def setup_logging() -> None:
    # Formato común
    log_format = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    
    # Handler para consola
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(log_format))
    
    # Handler para archivo
    file_handler = logging.FileHandler("server_debug.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(log_format))
    
    # Configuración raíz
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Limpiar handlers previos si existen
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
        
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    # Opcional: Desactivar loggers ruidosos
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

logger = logging.getLogger("midas")
