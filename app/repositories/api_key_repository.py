"""Este archivo se mantiene solo por compatibilidad de imports.

El código real vive ahora en app/repositories/api_key/:
  - key_repository.py   → CRUD de API Keys
  - usage_repository.py → Logging y cuotas
  - stats_repository.py → Métricas y estadísticas
  - composite.py        → Fachada compuesta (APIKeyRepository)
"""
from app.repositories.api_key import APIKeyRepository  # noqa: F401

__all__ = ["APIKeyRepository"]
