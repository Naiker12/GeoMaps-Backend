"""Regresiones de modelos, cuotas, revocación y respuestas de error."""

import importlib
import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from backend_test_environment import configure_test_environment

configure_test_environment()

from sqlalchemy.dialects import postgresql
from starlette.requests import Request
from app.core import exceptions
from app.db import base
from app.db.session import Base


class ModelCompatibilityTests(unittest.TestCase):
    def test_legacy_imports_reuse_canonical_models_without_registering_duplicates(self):
        for name, symbol in (("user", "User"), ("user_session", "UserSession"), ("admin", "Admin")):
            canonical = importlib.import_module(f"app.db.models.{name}")
            before = set(Base.metadata.tables)
            legacy = importlib.import_module(f"app.domain.models.{name}")
            self.assertIs(getattr(legacy, symbol), getattr(canonical, symbol))
            self.assertEqual(set(Base.metadata.tables), before)
        self.assertIs(
            importlib.import_module("app.domain.models.user").UserRole,
            importlib.import_module("app.db.models.user").UserRole,
        )


class ErrorResponseTests(unittest.IsolatedAsyncioTestCase):
    def request(self, origin=None):
        return Request({"type": "http", "method": "GET", "path": "/test", "headers":
            [(b"origin", origin.encode())] if origin else []})

    async def test_internal_errors_do_not_disclose_exception_text(self):
        with self.assertLogs(exceptions.logger, level="ERROR"):
            response = await exceptions.global_exception_handler(self.request(), RuntimeError("database-password=secret"))
        self.assertEqual(response.status_code, 500)
        self.assertNotIn(b"secret", response.body)
        self.assertEqual(json.loads(response.body)["error"]["message"], "Error interno del servidor")

    async def test_cors_headers_only_allow_configured_or_local_origins(self):
        config = SimpleNamespace(BACKEND_CORS_ORIGINS=["https://maps.example.com/"], FRONTEND_URL="https://front.example.com")
        with patch.object(exceptions, "settings", config):
            for origin in ("https://maps.example.com", "https://front.example.com", "http://localhost:5173"):
                response = await exceptions.midas_exception_handler(self.request(origin), exceptions.ValidationException("invalid"))
                self.assertEqual(response.headers["access-control-allow-origin"], origin)
                self.assertEqual(response.headers["vary"], "Origin")
            for origin in (None, "null", "https://localhost.evil.test:5173", "https://other.example.com"):
                response = await exceptions.midas_exception_handler(self.request(origin), exceptions.ValidationException("invalid"))
                self.assertNotIn("access-control-allow-origin", response.headers)






if __name__ == "__main__":
    unittest.main()
