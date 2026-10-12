"""RPM: contrato HTTP y script real en Redis local aislado."""

import asyncio
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from backend_test_environment import configure_test_environment

configure_test_environment()

from fastapi import HTTPException
from pydantic import ValidationError
from redis import Redis as SyncRedis
from redis.asyncio import Redis
from redis.exceptions import ConnectionError, TimeoutError
from app.core.security import api_key_rate_limit as limiter
from app.schemas.api_key import APIKeyCreate, APIKeyUpdate


class APIKeyRateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_limit_does_not_connect(self):
        with patch.object(limiter.Redis, "from_url") as connect:
            await limiter.enforce_api_key_rate_limit(uuid.uuid4(), None)
        connect.assert_not_called()

    async def test_rejection_has_retry_after_and_closes_client(self):
        client = AsyncMock()
        client.eval.return_value = [0, 23]
        context = AsyncMock()
        context.__aenter__.return_value = client
        with patch.object(limiter.Redis, "from_url", return_value=context):
            with self.assertRaises(HTTPException) as caught:
                await limiter.enforce_api_key_rate_limit(uuid.uuid4(), 3)
        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(caught.exception.headers, {"Retry-After": "23"})
        context.__aexit__.assert_awaited_once()

    async def test_unavailable_redis_returns_503(self):
        context = AsyncMock()
        context.__aenter__.side_effect = ConnectionError("unavailable")
        with patch.object(limiter.Redis, "from_url", return_value=context), self.assertLogs(limiter.logger, level="ERROR"):
            with self.assertRaises(HTTPException) as caught:
                await limiter.enforce_api_key_rate_limit(uuid.uuid4(), 3)
        self.assertEqual(caught.exception.status_code, 503)

    def test_non_positive_limits_are_invalid(self):
        for schema in (APIKeyCreate, APIKeyUpdate):
            for limit in (0, -1):
                with self.subTest(schema=schema.__name__, limit=limit), self.assertRaises(ValidationError):
                    schema(rate_limit_rpm=limit)
            self.assertEqual(schema(rate_limit_rpm=2).rate_limit_rpm, 2)
            self.assertIsNone(schema(rate_limit_rpm=None).rate_limit_rpm)


@unittest.skipUnless(shutil.which("redis-server"), "redis-server no está disponible")
class RedisScriptIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="geomaps-redis-test-")
        cls.addClassCleanup(cls.directory.cleanup)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cls.url = f"redis://127.0.0.1:{port}"
        cls.process = subprocess.Popen([
            shutil.which("redis-server"), "--bind", "127.0.0.1", "--port", str(port),
            "--save", "", "--appendonly", "no", "--dir", cls.directory.name,
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        cls.addClassCleanup(cls.stop_server)
        client = SyncRedis.from_url(cls.url, socket_connect_timeout=0.2, socket_timeout=0.2)
        try:
            for _ in range(40):
                try:
                    if client.ping():
                        return
                except (ConnectionError, TimeoutError):
                    time.sleep(0.05)
            raise RuntimeError("El Redis aislado de pruebas no arrancó")
        finally:
            client.close()

    @classmethod
    def stop_server(cls):
        cls.process.terminate()
        cls.process.wait(timeout=5)

    async def test_concurrent_requests_do_not_exceed_limit(self):
        async with Redis.from_url(self.url, socket_connect_timeout=3, socket_timeout=3) as client:
            key = f"test:{uuid.uuid4()}"
            results = await asyncio.gather(*[
                client.eval(limiter.RATE_LIMIT_SCRIPT, 1, key, 5) for _ in range(30)
            ])
            self.assertEqual(sum(result[0] for result in results), 5)
            self.assertEqual(int(await client.get(key)), 5)
            self.assertGreater(await client.ttl(key), 0)

    async def test_expired_window_accepts_request_again(self):
        async with Redis.from_url(self.url, socket_connect_timeout=3, socket_timeout=3) as client:
            key = f"test:{uuid.uuid4()}"
            self.assertEqual((await client.eval(limiter.RATE_LIMIT_SCRIPT, 1, key, 1))[0], 1)
            self.assertEqual((await client.eval(limiter.RATE_LIMIT_SCRIPT, 1, key, 1))[0], 0)
            await client.pexpire(key, 1)
            await asyncio.sleep(0.02)
            self.assertEqual((await client.eval(limiter.RATE_LIMIT_SCRIPT, 1, key, 1))[0], 1)

    async def test_key_isolation_and_rejection_does_not_extend_ttl(self):
        async with Redis.from_url(self.url, socket_connect_timeout=3, socket_timeout=3) as client:
            key = f"test:{uuid.uuid4()}"
            await client.eval(limiter.RATE_LIMIT_SCRIPT, 1, key, 1)
            await client.expire(key, 20)
            denied = await client.eval(limiter.RATE_LIMIT_SCRIPT, 1, key, 1)
            self.assertEqual(denied[0], 0)
            self.assertLessEqual(await client.ttl(key), 20)
            self.assertEqual((await client.eval(limiter.RATE_LIMIT_SCRIPT, 1, f"{key}:other", 1))[0], 1)


if __name__ == "__main__":
    unittest.main()
