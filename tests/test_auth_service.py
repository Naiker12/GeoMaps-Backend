"""Sincronización de perfiles sin asignación implícita de privilegios."""

import threading
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from backend_test_environment import configure_test_environment

configure_test_environment()

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
with patch("supabase.create_client"):
    from app.application.auth import service as auth
    from app.api.v1 import auth as routes
from app.db.models.user import UserRole
from app.schemas.user_schema import UserProfileUpdate


class AuthServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with patch.object(auth, "create_client"):
            self.service = auth.AuthService()
        self.db = AsyncMock()
        self.db.add = Mock()

    async def test_new_profiles_do_not_gain_admin_role_from_email_or_metadata(self):
        for email in ("admin@geomaps.com", "person@geomaps.com", "user@example.com"):
            user = await self.service._create_local_user({
                "sub": str(uuid.uuid4()), "email": email,
                "user_metadata": {"role": "SUPER_ADMIN"},
            }, self.db)
            self.assertEqual(user.role, UserRole.USER)

    async def test_null_metadata_is_supported(self):
        user = await self.service._create_local_user({
            "sub": str(uuid.uuid4()), "email": "user@example.com",
            "user_metadata": None, "app_metadata": None,
        }, self.db)
        self.assertEqual(user.full_name, "user")
        self.assertEqual(user.auth_provider, "supabase")

    async def test_invalid_identity_is_rejected_before_database(self):
        for payload in ({"sub": "invalid", "email": "user@example.com"},
                        {"sub": str(uuid.uuid4()), "email": None}, {"sub": {}}):
            with self.assertRaises(HTTPException) as caught:
                await self.service.start_user_session(payload, self.db)
            self.assertEqual(caught.exception.status_code, 401)
        self.db.execute.assert_not_awaited()

    async def test_inactive_user_is_not_mutated(self):
        user = SimpleNamespace(is_active=False, email="old@example.com", supabase_id=None)
        self.db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=user))
        with self.assertRaises(HTTPException) as caught:
            await self.service.start_user_session({"sub": str(uuid.uuid4()), "email": "new@example.com"}, self.db)
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(user.email, "old@example.com")
        self.assertIsNone(user.supabase_id)
        self.db.commit.assert_not_awaited()

    async def test_database_flush_failure_rolls_back_and_preserves_cause(self):
        failure = SQLAlchemyError("private database details")
        self.db.flush.side_effect = failure
        with self.assertLogs(auth.logger, level="CRITICAL"), self.assertRaises(HTTPException) as caught:
            await self.service._create_local_user({"sub": str(uuid.uuid4()), "email": "user@example.com"}, self.db)
        self.assertEqual(caught.exception.status_code, 500)
        self.assertIs(caught.exception.__cause__, failure)
        self.assertNotIn("private", caught.exception.detail)
        self.db.rollback.assert_awaited_once()

    async def test_password_verification_does_not_block_event_loop(self):
        self.db.execute.return_value = Mock(scalar_one_or_none=Mock(
            return_value=SimpleNamespace(is_active=True, password_hash="hash")
        ))
        loop_thread = threading.get_ident()
        worker_threads = []

        def verify(*args):
            worker_threads.append(threading.get_ident())
            return False

        with patch.object(auth, "verify_password", side_effect=verify):
            result = await self.service.login_admin("user@example.com", "password", self.db)
        self.assertFalse(result.success)
        self.assertNotEqual(worker_threads[0], loop_thread)

    async def test_profile_route_does_not_repeat_service_transaction(self):
        user = SimpleNamespace(full_name="test")
        with patch.object(routes.auth_service, "update_user_profile", new_callable=AsyncMock, return_value=user):
            result = await routes.update_my_profile(UserProfileUpdate(full_name="test"), self.db, user)
        self.assertIs(result, user)
        self.db.commit.assert_not_awaited()
        self.db.refresh.assert_not_awaited()

    async def test_admin_login_uses_canonical_user_for_profile_token_and_session(self):
        admin = SimpleNamespace(id=uuid.uuid4(), email="admin@example.com", is_active=True, password_hash="hash", is_superadmin=True)
        user = SimpleNamespace(id=uuid.uuid4(), email=admin.email, full_name="Admin", role=UserRole.ADMIN,
                               is_active=True, avatar_url=None, created_at=datetime.now(timezone.utc))
        self.db.execute.side_effect = [Mock(scalar_one_or_none=Mock(return_value=admin)),
                                       Mock(scalar_one_or_none=Mock(return_value=user))]

        async def flush():
            self.db.add.call_args.args[0].id = uuid.uuid4()

        self.db.flush.side_effect = flush
        with patch.object(auth, "verify_password", return_value=True), patch.object(auth, "create_access_token", return_value="token") as create:
            result = await self.service.login_admin(admin.email, "password", self.db)
        self.assertTrue(result.success)
        self.assertEqual(result.user.id, str(user.id))
        self.assertEqual(self.db.add.call_args.args[0].user_id, user.id)
        self.assertEqual(create.call_args.args[0]["sub"], str(user.id))
        self.assertEqual(create.call_args.args[0]["role"], UserRole.ADMIN)

    async def test_legacy_admin_credentials_cannot_promote_unprivileged_user(self):
        admin = SimpleNamespace(email="admin@example.com", is_active=True, password_hash="hash", is_superadmin=True)
        for user in (None, SimpleNamespace(is_active=True, role=UserRole.USER), SimpleNamespace(is_active=False, role=UserRole.ADMIN)):
            self.db.execute.side_effect = [Mock(scalar_one_or_none=Mock(return_value=admin)),
                                           Mock(scalar_one_or_none=Mock(return_value=user))]
            with patch.object(auth, "verify_password", return_value=True):
                result = await self.service.login_admin(admin.email, "password", self.db)
            self.assertFalse(result.success)
        self.db.add.assert_not_called()
        self.db.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
