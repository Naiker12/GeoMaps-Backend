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
from app.db.models.api_key import APIKeyStatus
from app.db.session import Base
from app.repositories.api_key.usage_repository import APIKeyUsageRepository
from app.services.api_keys import service as api_key_service


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


class QuotaRepositoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = AsyncMock()
        self.db.execute.return_value = Mock(scalar=Mock(return_value=4))
        self.repository = APIKeyUsageRepository(self.db)
        self.user_id = uuid.uuid4()

    async def test_usage_window_is_bound_as_interval_and_filters_success(self):
        self.assertEqual(await self.repository.get_user_usage_count(self.user_id, 7), 4)
        compiled = self.db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
        self.assertIn(timedelta(days=7), compiled.params.values())
        self.assertIn(self.user_id, compiled.params.values())
        self.assertIn("status_code <", str(compiled))
        await self.repository.get_user_total_usage_count(self.user_id, 7)
        compiled = self.db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
        self.assertNotIn("status_code <", str(compiled))

    async def test_invalid_windows_do_not_query_database(self):
        for days in (0, -1, True, "1'; DROP TABLE users; --"):
            with self.assertRaises(ValueError):
                await self.repository.get_user_usage_count(self.user_id, days)
        self.db.execute.assert_not_awaited()

    async def test_quota_boundary_matches_reported_status(self):
        for used in (8, 9, 10, 12):
            self.db.execute.return_value.scalar.return_value = used
            status = await self.repository.get_quota_status(self.user_id)
            self.assertEqual(status["remaining"], max(0, 10 - used))
            self.assertEqual(status["is_blocked"], used >= 10)
            self.assertEqual(await self.repository.check_daily_quota(self.user_id), used < 10)


class KeyRevocationTests(unittest.IsolatedAsyncioTestCase):
    async def test_revocation_uses_utc_and_preserves_owner_authorization(self):
        service = api_key_service.APIKeyService(AsyncMock())
        owner_id, key_id = uuid.uuid4(), uuid.uuid4()
        key = SimpleNamespace(id=key_id, user_id=owner_id)
        service.repository = SimpleNamespace(get=AsyncMock(return_value=key), update=AsyncMock(return_value=key))
        now = datetime(2026, 10, 11, tzinfo=timezone.utc)
        with patch.object(api_key_service, "get_utc_now", return_value=now):
            self.assertIsNone(await service.revoke_api_key(key_id, uuid.uuid4()))
            service.repository.update.assert_not_awaited()
            self.assertIs(await service.revoke_api_key(key_id, owner_id), key)
        self.assertEqual(service.repository.update.call_args.args[1], {
            "status": APIKeyStatus.REVOKED, "revoked_at": now, "revoked_by": owner_id,
        })


if __name__ == "__main__":
    unittest.main()
