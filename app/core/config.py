from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # Supabase Configuration
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    
    @property
    def SUPABASE_KEY(self) -> str:
        return self.SUPABASE_ANON_KEY

    # Database Configuration
    DATABASE_URL: str
    
    # Frontend Info
    FRONTEND_URL: str = "http://localhost:5173"

    # Security
    JWT_SECRET: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Supabase JWT Configuration (Secret used to sign JWTs by Supabase)
    # Por defecto en Supabase suele ser el mismo JWT_SECRET pero para validación
    # externa se usa para verificar el token del cliente.
    SUPABASE_JWT_SECRET: str
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
