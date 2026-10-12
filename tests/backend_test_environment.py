"""Configuración ficticia compartida; aplicar antes de importar la aplicación."""

import os


def configure_test_environment() -> None:
    os.environ.update({
        "DATABASE_URL": "postgresql+psycopg://test:test@localhost/geomaps_test",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_ANON_KEY": "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.dGVzdA",
        "SUPABASE_SERVICE_KEY": "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.dGVzdA",
        "SUPABASE_JWT_SECRET": "test-supabase-secret",
        "SUPABASE_JWT_ISSUER": "https://example.supabase.co/auth/v1",
        "SECRET_KEY": "test-local-secret",
        "GOOGLE_API": "test-google-key",
        "REDIS_URL": "redis://127.0.0.1:1",
    })
