"""Lectura limitada y limpieza de archivos GIS de capas."""

import io
import json
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend_test_environment import configure_test_environment
configure_test_environment()

from fastapi import UploadFile
with patch("supabase.create_client"):
    from app.services.layers import service as layers


class LayerFileTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = layers.LayerService(AsyncMock())

    async def test_geojson_is_read_in_worker_and_preserved_for_upload(self):
        content = b'{"type":"FeatureCollection","features":[]}'
        file = UploadFile(file=io.BytesIO(content), filename="map.GEOJSON")
        original = self.service._parse_content
        worker_threads = []
        loop_thread = threading.get_ident()

        def parse(filename, content):
            worker_threads.append(threading.get_ident())
            return original(filename, content)

        with patch.object(self.service, "_parse_content", side_effect=parse):
            self.assertEqual(await self.service._parse_file(file), json.loads(content))
        self.assertNotEqual(worker_threads[0], loop_thread)
        self.assertEqual(await file.read(), content)

    async def test_oversized_file_does_not_reach_parser(self):
        file = UploadFile(file=io.BytesIO(b"123456789"), filename="map.geojson")
        with patch.object(layers, "MAX_FILE_SIZE", 4), patch.object(self.service, "_parse_content") as parse:
            with self.assertRaises(layers.FileTooLargeError):
                await self.service._parse_file(file)
        parse.assert_not_called()
        self.assertEqual(file.file.tell(), 0)

    async def test_zip_temporary_file_is_removed_after_reader_failure(self):
        paths = []

        def fail(uri):
            path = Path(uri.removeprefix("zip://"))
            self.assertTrue(path.exists())
            paths.append(path)
            raise ValueError("invalid zip")

        file = UploadFile(file=io.BytesIO(b"zip"), filename="map.zip")
        with patch.object(layers.gpd, "read_file", side_effect=fail):
            with self.assertRaisesRegex(ValueError, "invalid zip"):
                await self.service._parse_file(file)
        self.assertFalse(paths[0].exists())
        self.assertEqual(file.file.tell(), 0)

    async def test_absent_filename_is_a_controlled_validation_error(self):
        with self.assertRaisesRegex(ValueError, "Formato no soportado"):
            await self.service._parse_file(UploadFile(file=io.BytesIO(b"data")))


if __name__ == "__main__":
    unittest.main()
