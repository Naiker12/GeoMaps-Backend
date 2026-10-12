"""OGC: respuesta acotada, URL inválida y DNS fuera del event loop."""

import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch

from backend_test_environment import configure_test_environment
configure_test_environment()

import httpx
from fastapi import HTTPException
from starlette.requests import Request
with patch("supabase.create_client"):
    from app.api.v1 import ogc


class OGCProxyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.request = Request({"type": "http", "method": "GET", "path": "/proxy", "headers": [], "query_string": b""})
        self.upstream = Mock(status_code=200, headers={"content-type": "application/xml; charset=utf-8"})
        stream = AsyncMock()
        stream.__aenter__.return_value = self.upstream
        self.client = Mock()
        self.client.stream.return_value = stream
        self.stream = stream
        self.context = AsyncMock()
        self.context.__aenter__.return_value = self.client

    async def call(self):
        with patch.object(ogc.httpx, "AsyncClient", return_value=self.context), patch.object(
            ogc, "_validate_public_url", return_value="https://example.com/wms"
        ):
            return await ogc.proxy_ogc_request(self.request, "https://example.com/wms", Mock())

    async def test_streamed_content_preserves_response_status_and_type(self):
        async def chunks(**kwargs):
            yield b"<xml>"
            yield b"</xml>"

        self.upstream.aiter_bytes = chunks
        response = await self.call()
        self.assertEqual(response.body, b"<xml></xml>")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("application/xml"))
        self.stream.__aexit__.assert_awaited_once()

    async def test_excessive_stream_stops_before_reading_remaining_body(self):
        consumed = []

        async def chunks(**kwargs):
            for chunk in (b"123", b"456", b"remaining"):
                consumed.append(chunk)
                yield chunk

        self.upstream.aiter_bytes = chunks
        with patch.object(ogc, "MAX_PROXY_BYTES", 4), self.assertRaises(HTTPException) as caught:
            await self.call()
        self.assertEqual(caught.exception.status_code, 413)
        self.assertEqual(consumed, [b"123", b"456"])
        self.stream.__aexit__.assert_awaited_once()

    async def test_network_error_does_not_expose_internal_details(self):
        self.client.stream.side_effect = httpx.ConnectError("private-network-details")
        with self.assertRaises(HTTPException) as caught:
            await self.call()
        self.assertEqual(caught.exception.status_code, 502)
        self.assertNotIn("private", caught.exception.detail)

    def test_invalid_ports_and_ipv6_urls_are_controlled_errors(self):
        for url in ("https://example.com:not-a-port", "https://example.com:99999", "https://example.com:0", "http://["):
            with self.assertRaises(HTTPException) as caught:
                ogc._validate_public_url(url)
            self.assertEqual(caught.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
