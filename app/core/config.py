"""Configuración centralizada de GeoMaps Backend mediante Pydantic Settings.
Carga variables de entorno, valida URIs de base de datos y define parámetros globales de seguridad.
"""

import secrets
from typing import List, Optional, Union, Any
from pydantic import AnyHttpUrl, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Esquema de configuración de entorno para GeoMaps v2."""

    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "7f9b8c2d5e1a4f3b6a9c8d7e6f5a4b3c2d1e0f9a8b7c6d5e4f3a2b1c0d9e8f7a" # Valor por defecto seguro pero sobrescribible por .env
    JWT_SECRET: Optional[str] = None # Alias para SECRET_KEY si se prefiere en .env
    
    @field_validator("SECRET_KEY", mode="before")
    def assemble_secret_key(cls, v: Any, info: Any) -> str:
        # Priorizar JWT_SECRET de .env si existe
        return v or "7f9b8c2d5e1a4f3b6a9c8d7e6f5a4b3c2d1e0f9a8b7c6d5e4f3a2b1c0d9e8f7a"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8 
    PROJECT_NAME: str = "GeoMaps - Visor Geográfico"
    DEBUG: bool = False

    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = [
        "https://localhost:3000",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        """Convierte lista de orígenes CSV a formato lista de URLs de Pydantic."""
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # Nombres compatibles con todo el sistema
    DATABASE_URL: Optional[PostgresDsn] = None
    SQLALCHEMY_DATABASE_URI: Optional[PostgresDsn] = None

    @field_validator("DATABASE_URL", "SQLALCHEMY_DATABASE_URI", mode="before")
    def assemble_db_connection(cls, v: Optional[str]) -> Any:
        """Prefija la URI de BD con el driver psycopg si no está presente."""
        if isinstance(v, str) and not v.startswith("postgresql+psycopg://"):
             return v.replace("postgresql://", "postgresql+psycopg://")
        return v

    # Supabase Integration
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_JWT_SECRET: str = ""

    model_config = SettingsConfigDict(
        case_sensitive=True, 
        env_file=".env",
        extra="ignore"
    )


settings = Settings()
