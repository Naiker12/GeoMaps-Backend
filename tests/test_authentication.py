"""Regresiones de autenticación sin conexión a servicios externos.

Ejecutar desde la raíz: python -m unittest discover -s tests -v
"""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

# Estos valores se usan solo al importar la configuración en este proceso de pruebas.
from backend_test_environment import configure_test_environment

configure_test_environment()

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request

from app.db import base  # Registrar relaciones ORM antes de construir consultas.
from app.api import deps
from app.api.v1.auth import router as auth_router
from app.core.security import dependencies, identity
from app.core.security.cookies import is_local_origin
from app.schemas.user_schema import UserProfileUpdate, UserUpdate, UserCreate


def make_request(headers=None):
    return Request({
        "type": "http", "method": "GET", "path": "/auth/me",
        "headers": [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()],
        "query_string": b"",
    })


def make_db(value):
    result = Mock()
    result.scalar_one_or_none.return_value = value
    return SimpleNamespace(execute=AsyncMock(return_value=result), commit=AsyncMock())


class TokenIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_jwt_dependencies_reject_inactive_users(self):
        user = SimpleNamespace(is_active=False)
        db = make_db(user)
        request = make_request({"Authorization": "Bearer test"})
        with patch.object(identity, "decode_token", return_value={"sub": str(uuid.uuid4())}):
            for resolve in (
                lambda: deps.get_current_user(request, db, token="test"),
                lambda: dependencies.get_current_user(request, db),
                lambda: deps.get_current_user_optional(request, db, token="test"),
            ):
                with self.assertRaises(HTTPException) as caught:
                    await resolve()
                self.assertEqual(caught.exception.status_code, 403)

    async def test_optional_auth_preserves_database_errors(self):
        db = make_db(None)
        db.execute.side_effect = RuntimeError("database unavailable")
        with patch.object(identity, "decode_token", return_value={"sub": str(uuid.uuid4())}):
            with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                await deps.get_current_user_optional(make_request(), db, token="test")

    async def test_optional_auth_accepts_absent_or_expired_token_as_anonymous(self):
        db = make_db(None)
        self.assertIsNone(await deps.get_current_user_optional(make_request(), db, token=None))
        with patch.object(identity, "decode_token", return_value=None), patch.object(
            identity, "decode_supabase_token", return_value=None
        ):
            self.assertIsNone(await deps.get_current_user_optional(make_request(), db, token="expired"))
        db.execute.assert_not_awaited()

    async def test_malformed_identity_is_unauthorized(self):
        with patch.object(identity, "decode_token", return_value={"sub": "invalid-uuid"}):
            with self.assertRaises(HTTPException) as caught:
                await identity.resolve_token_user(make_db(None), "test")
        self.assertEqual(caught.exception.status_code, 401)

    async def test_local_token_requires_valid_owned_session_when_sid_is_present(self):
        user = SimpleNamespace(id=uuid.uuid4(), is_active=True)
        session_id = uuid.uuid4()
        db = make_db(user)
        db.execute.side_effect = [Mock(scalar_one_or_none=Mock(return_value=user)),
                                  Mock(scalar_one_or_none=Mock(return_value=session_id))]
        with patch.object(identity, "decode_token", return_value={"sub": str(user.id), "sid": str(session_id)}):
            self.assertIs(await identity.resolve_token_user(db, "token"), user)
        statement = db.execute.call_args.args[0]
        self.assertIn(user.id, statement.compile().params.values())
        self.assertIn(session_id, statement.compile().params.values())
        self.assertIn("logout_at IS NULL", str(statement))
        self.assertIn("expires_at >", str(statement))

    async def test_revoked_or_expired_session_rejects_otherwise_valid_token(self):
        user = SimpleNamespace(id=uuid.uuid4(), is_active=True)
        db = make_db(user)
        db.execute.side_effect = [Mock(scalar_one_or_none=Mock(return_value=user)),
                                  Mock(scalar_one_or_none=Mock(return_value=None))]
        with patch.object(identity, "decode_token", return_value={"sub": str(user.id), "sid": str(uuid.uuid4())}):
            with self.assertRaises(HTTPException) as caught:
                await identity.resolve_token_user(db, "token")
        self.assertEqual(caught.exception.status_code, 401)

    async def test_invalid_session_id_is_unauthorized(self):
        user = SimpleNamespace(id=uuid.uuid4(), is_active=True)
        db = make_db(user)
        with patch.object(identity, "decode_token", return_value={"sub": str(user.id), "sid": "invalid"}):
            with self.assertRaises(HTTPException) as caught:
                await identity.resolve_token_user(db, "token")
        self.assertEqual(caught.exception.status_code, 401)

    async def test_external_subject_only_matches_supabase_identity_column(self):
        user = SimpleNamespace(id=uuid.uuid4(), is_active=True)
        db = make_db(user)
        with patch.object(identity, "decode_token", return_value=None), patch.object(
            identity, "decode_supabase_token", return_value={"sub": str(uuid.uuid4())}
        ):
            self.assertIs(await identity.resolve_token_user(db, "external"), user)
        statement = str(db.execute.call_args.args[0])
        self.assertIn("WHERE users.supabase_id =", statement)
        self.assertNotIn(" OR ", statement)






class ProfileRouteTests(unittest.TestCase):
    def test_retired_api_key_cannot_authenticate_profile(self):
        app = FastAPI()
        app.include_router(auth_router, prefix="/api/v1")
        for suffix, headers in (("", {"X-API-Key": "retired-key"}), ("?api_key=retired-key", {})):
            response = TestClient(app).get("/api/v1/auth/me" + suffix, headers=headers)
            self.assertEqual(response.status_code, 401)

    def test_profile_still_resolves_session_token(self):
        app = FastAPI()
        app.include_router(auth_router, prefix="/api/v1")
        user = SimpleNamespace(id=uuid.uuid4(), email="user@example.com", role="USER", is_active=True, created_at=datetime.now(timezone.utc))
        with patch.object(deps, "resolve_token_user", new_callable=AsyncMock, return_value=user) as resolve:
            response = TestClient(app).get("/api/v1/auth/me", headers={"Authorization": "Bearer session-token"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["id"], str(user.id))
        self.assertEqual(resolve.await_args.args[1], "session-token")


    def test_profile_changes_cannot_include_administrative_fields(self):
        for field, value in (("role", "SUPER_ADMIN"), ("is_active", True)):
            with self.assertRaises(ValidationError):
                UserProfileUpdate.model_validate({field: value})
        self.assertEqual(UserUpdate(role="ADMIN").role, "ADMIN")

    def test_admin_user_roles_match_database_enum(self):
        for schema, values in ((UserUpdate, {}), (UserCreate, {"email": "user@example.com", "password": "test-password"})):
            for role in ("EDITOR", "unknown"):
                with self.assertRaises(ValidationError):
                    schema(**values, role=role)


class CookieOriginTests(unittest.TestCase):
    def test_local_hosts_are_matched_exactly(self):
        for origin in ("http://localhost:5173", "http://127.0.0.1:5173", "http://[::1]:5173"):
            self.assertTrue(is_local_origin(origin), origin)
        for origin in (None, "null", "http://[", "https://localhost.evil.test", "https://evil.test/localhost", "https://127.0.0.1.evil.test", "file://localhost"):
            self.assertFalse(is_local_origin(origin), origin)


if __name__ == "__main__":
    unittest.main()
