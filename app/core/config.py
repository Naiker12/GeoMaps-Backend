"""Configuración centralizada de GeoMaps Backend mediante Pydantic Settings."""

from typing import List, Optional, Union, Any
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Esquema de configuración de entorno para GeoMaps v2."""

    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "GeoMaps - Visor Geográfico"
    DEBUG: bool = False

    # Seguridad
    SECRET_KEY: Optional[str] = None
    JWT_SECRET: Optional[str] = None
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    @field_validator("SECRET_KEY", mode="before")
    def assemble_secret_key(cls, v: Any, info: Any) -> str:
        return v or info.data.get("JWT_SECRET") or ""

    # CORS
    FRONTEND_URL: str = "http://localhost:5173"
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # Base de datos
    DATABASE_URL: str

    @field_validator("DATABASE_URL", mode="before")
    def assemble_db_connection(cls, v: Optional[str]) -> Any:
        if isinstance(v, str) and not v.startswith("postgresql+psycopg://"):
            return v.replace("postgresql://", "postgresql+psycopg://")
        return v

    # Supabase
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_KEY: Optional[str] = None
    SUPABASE_JWT_SECRET: str

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        extra="ignore"
    )


settings = Settings()