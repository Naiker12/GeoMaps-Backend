"""Reservas, finalización idempotente, middleware y upsert real portable."""

import asyncio
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from backend_test_environment import configure_test_environment
configure_test_environment()

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import Column, JSON, MetaData, Table, Uuid, create_engine, select
from sqlalchemy.dialects import postgresql
from app.api import middleware
from app.db import base
from app.db.models.api_key import APIKeyDailyStats
from app.repositories.api_key.usage_repository import APIKeyUsageRepository


class AccountingRepositoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = AsyncMock()
        self.db.add = Mock()
        self.repository = APIKeyUsageRepository(self.db)
        self.key_id, self.user_id = uuid.uuid4(), uuid.uuid4()
        self.usage = dict(api_key_id=self.key_id, user_id=self.user_id,
                          endpoint="/api/v1/test", method="GET", status_code=200,
                          response_time_ms=10, tokens_used=2)

    async def test_reservation_locks_user_and_is_committed_before_admission(self):
        self.db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=self.user_id))
        with patch.object(self.repository, "check_daily_quota", new_callable=AsyncMock, return_value=True):
            reservation_id = await self.repository.reserve_daily_quota(
                api_key_id=self.key_id, user_id=self.user_id, endpoint="/test", method="GET"
            )
        statement = self.db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
        self.assertIn("FOR UPDATE", str(statement))
        self.assertIn(self.user_id, statement.params.values())
        log = self.db.add.call_args.args[0]
        self.assertEqual(log.id, reservation_id)
        self.assertEqual(log.status_code, 102)
        self.assertTrue(log.quota_pending)
        self.db.commit.assert_awaited_once()

    async def test_exhausted_quota_releases_lock_without_admission(self):
        self.db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=self.user_id))
        with patch.object(self.repository, "check_daily_quota", new_callable=AsyncMock, return_value=False):
            result = await self.repository.reserve_daily_quota(
                api_key_id=self.key_id, user_id=self.user_id, endpoint="/test", method="GET"
            )
        self.assertIsNone(result)
        self.db.add.assert_not_called()
        self.db.commit.assert_not_awaited()
        self.db.rollback.assert_awaited_once()

    async def test_duplicate_finalization_cannot_increment_statistics_twice(self):
        self.db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=None))
        self.assertIsNone(await self.repository.log_usage(**self.usage, reservation_id=uuid.uuid4()))
        self.assertEqual(self.db.execute.await_count, 1)
        self.db.add.assert_not_called()
        statement = self.db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
        self.assertIn("quota_pending IS true", str(statement))
        self.assertIn(self.key_id, statement.params.values())
        self.assertIn(self.user_id, statement.params.values())

    async def test_failed_response_finishes_reservation_and_counts_error_once(self):
        requested_at = datetime(2026, 10, 10, 23, 59, tzinfo=timezone.utc)
        log = SimpleNamespace(requested_at=requested_at)
        self.db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=log))
        self.usage["status_code"] = 429
        await self.repository.log_usage(**self.usage, reservation_id=uuid.uuid4())
        update = self.db.execute.call_args_list[0].args[0].compile(dialect=postgresql.dialect())
        self.assertEqual(update.params["status_code"], 429)
        self.assertFalse(update.params["quota_pending"])
        upsert = self.db.execute.call_args_list[-1].args[0].compile(dialect=postgresql.dialect())
        self.assertIn("ON CONFLICT (api_key_id, stat_date) DO UPDATE", str(upsert))
        self.assertEqual(upsert.params["error_requests"], 1)
        self.assertEqual(upsert.params["success_requests"], 0)
        self.assertEqual(upsert.params["stat_date"], datetime(2026, 10, 10))
        self.db.add.assert_not_called()
        self.db.commit.assert_awaited_once()


class AccountingMiddlewareTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.add_middleware(middleware.APIKeyUsageMiddleware)
        self.key_id, self.user_id, self.reservation_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        self.service = SimpleNamespace(log_api_usage=AsyncMock(), log_failed_attempt=AsyncMock())
        self.session = AsyncMock()
        self.session.__aenter__.return_value = Mock()
        self.result_status = 200
        self.has_reservation = True
        self.fail_handler = False

        @self.app.get("/api/v1/test")
        async def endpoint(request: Request):
            request.state.api_key_id = self.key_id
            request.state.user_id = self.user_id
            if self.has_reservation:
                request.state.api_key_quota_reservation_id = self.reservation_id
            if self.fail_handler:
                raise RuntimeError("handler failed")
            return JSONResponse({"ok": True}, status_code=self.result_status)

    def request(self, headers=None):
        with patch.object(middleware, "SessionLocal", return_value=self.session) as factory, patch.object(
            middleware, "APIKeyService", return_value=self.service
        ), TestClient(self.app, raise_server_exceptions=False) as client:
            response = client.get("/api/v1/test", headers=headers or {"X-API-Key": "key12345"})
        return response, factory

    def test_response_waits_for_finalization_and_passes_reservation(self):
        response, _ = self.request()
        self.assertEqual(response.status_code, 200)
        self.assertIn("X-Process-Time", response.headers)
        self.service.log_api_usage.assert_awaited_once()
        self.assertEqual(self.service.log_api_usage.call_args.kwargs["reservation_id"], self.reservation_id)
        self.session.__aexit__.assert_awaited_once()

    def test_downstream_429_finalizes_reservation_instead_of_skipping_it(self):
        self.result_status = 429
        response, _ = self.request()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(self.service.log_api_usage.call_args.kwargs["status_code"], 429)

    def test_unreserved_429_does_not_open_logging_session(self):
        self.result_status, self.has_reservation = 429, False
        _, factory = self.request()
        factory.assert_not_called()

    def test_logging_failure_preserves_business_response(self):
        self.service.log_api_usage.side_effect = RuntimeError("database unavailable")
        with self.assertLogs(middleware.logger, level="ERROR"):
            response, _ = self.request()
        self.assertEqual(response.status_code, 200)

    def test_logging_timeout_preserves_response_and_closes_session(self):
        async def slow_log(**kwargs):
            await asyncio.sleep(10)

        self.service.log_api_usage.side_effect = slow_log
        with patch.object(middleware, "USAGE_LOG_TIMEOUT_SECONDS", 0.01), self.assertLogs(middleware.logger, level="ERROR"):
            response, _ = self.request()
        self.assertEqual(response.status_code, 200)
        self.session.__aexit__.assert_awaited_once()

    def test_requests_without_api_key_do_not_open_logging_session(self):
        response, factory = self.request({"Accept": "application/json"})
        self.assertEqual(response.status_code, 200)
        factory.assert_not_called()

    def test_handler_exception_finalizes_as_failure(self):
        self.fail_handler = True
        response, _ = self.request()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.service.log_api_usage.call_args.kwargs["status_code"], 500)


class StatisticsUpsertIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_upserts_preserve_every_increment_in_sqlite(self):
        # Ejecuta la misma expresión ON CONFLICT, compilada por SQLAlchemy
        # para SQLite. No sustituye una prueba del bloqueo de filas PostgreSQL.
        db = AsyncMock()
        db.add = Mock()
        await APIKeyUsageRepository(db).log_usage(
            api_key_id=uuid.uuid4(), user_id=uuid.uuid4(), endpoint="/test",
            method="GET", status_code=200, response_time_ms=1, tokens_used=2,
        )
        statement = db.execute.call_args_list[-1].args[0]
        with tempfile.TemporaryDirectory(prefix="geomaps-upsert-") as folder:
            engine = create_engine(f"sqlite:///{Path(folder) / 'stats.db'}", connect_args={"timeout": 10})
            try:
                metadata = MetaData()
                Table("users", metadata, Column("id", Uuid, primary_key=True))
                Table("api_keys", metadata, Column("id", Uuid, primary_key=True))
                table = APIKeyDailyStats.__table__.to_metadata(metadata)
                table.c.requests_by_endpoint.type = JSON()
                metadata.create_all(engine)

                def write(_):
                    with engine.begin() as connection:
                        connection.execute(statement)

                with ThreadPoolExecutor(max_workers=8) as workers:
                    await asyncio.to_thread(lambda: list(workers.map(write, range(30))))
                with engine.connect() as connection:
                    rows = connection.execute(select(table)).mappings().all()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["total_requests"], 30)
                self.assertEqual(rows[0]["success_requests"], 30)
                self.assertEqual(rows[0]["error_requests"], 0)
                self.assertEqual(rows[0]["tokens_used"], 60)
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
