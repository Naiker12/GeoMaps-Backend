"""Análisis de descargas y rechazo HTTP sin servicios externos."""

import io
import json
import threading
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from backend_test_environment import configure_test_environment

configure_test_environment()

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient

with patch("supabase.create_client"):
    from app.services.downloads import storage
    from app.api.v1 import downloads


class DownloadAnalysisTests(unittest.IsolatedAsyncioTestCase):
    def file(self, content, filename="datos.csv"):
        return UploadFile(file=io.BytesIO(content), filename=filename)

    async def test_csv_counts_records_with_quoted_newlines_and_restores_cursor(self):
        content = b'id,name\n1,"first\nsecond"\n2,last\n'
        file = self.file(content)
        metadata = await storage.DownloadStorageService.analyze_file(file)
        self.assertEqual(metadata, {"file_size_bytes": len(content), "content_count": 2})
        self.assertEqual(await file.read(), content)

    async def test_geojson_preserves_count_with_null_and_invalid_geometries(self):
        content = json.dumps({"features": [
            {"geometry": {"type": "Point"}}, {"geometry": None},
            {"geometry": "invalid"}, {"geometry": {"type": []}},
        ]}).encode()
        metadata = await storage.DownloadStorageService.analyze_file(self.file(content, "map.GEOJSON"))
        self.assertEqual(metadata["content_count"], 4)
        self.assertEqual(metadata["geometry_type"], "Point")

    async def test_invalid_json_keeps_size_and_logs_analysis_failure(self):
        file = self.file(b"{invalid", "map.json")
        with self.assertLogs(storage.logger, level="WARNING"):
            metadata = await storage.DownloadStorageService.analyze_file(file)
        self.assertEqual(metadata, {"file_size_bytes": 8})
        self.assertEqual(file.file.tell(), 0)

    async def test_oversize_is_not_analyzed_and_cursor_is_restored(self):
        file = self.file(b"123456789")
        with patch.object(storage, "MAX_FILE_SIZE", 4), patch.object(
            storage.DownloadStorageService, "_analyze_content"
        ) as analyze, patch.object(file, "read", wraps=file.read) as read:
            with self.assertRaises(storage.FileTooLargeError):
                await storage.DownloadStorageService.analyze_file(file)
        read.assert_awaited_once_with(5)
        analyze.assert_not_called()
        self.assertEqual(file.file.tell(), 0)

    async def test_empty_and_unsupported_files_keep_size(self):
        for content, filename in [(b"", "empty.csv"), (b"pdf", "document.pdf")]:
            with self.subTest(filename=filename):
                self.assertEqual(
                    await storage.DownloadStorageService.analyze_file(self.file(content, filename)),
                    {"file_size_bytes": len(content)},
                )

    async def test_csv_analysis_runs_in_worker(self):
        event_loop_thread = threading.get_ident()
        worker_threads = []
        original = storage.DownloadStorageService._analyze_csv

        def analyze(content):
            worker_threads.append(threading.get_ident())
            return original(content)

        with patch.object(storage.DownloadStorageService, "_analyze_csv", side_effect=analyze):
            await storage.DownloadStorageService.analyze_file(self.file(b"id\n1\n"))
        self.assertNotEqual(worker_threads[0], event_loop_thread)

    async def test_zip_temporary_file_is_removed_on_reader_failure(self):
        paths = []

        def fail(uri):
            path = Path(uri.removeprefix("zip://"))
            self.assertTrue(path.exists())
            paths.append(path)
            raise ValueError("invalid archive")

        with patch.object(storage.gpd, "read_file", side_effect=fail), self.assertLogs(
            storage.logger, level="WARNING"
        ):
            metadata = await storage.DownloadStorageService.analyze_file(self.file(b"zip", "map.zip"))
        self.assertEqual(metadata, {"file_size_bytes": 3})
        self.assertTrue(paths)
        self.assertFalse(paths[0].exists())

    async def test_zip_preserves_geometry_count_and_bounds(self):
        from shapely.geometry import Point

        dataframe = storage.gpd.GeoDataFrame(geometry=[Point(-75, 10), Point(-74, 11)])
        with patch.object(storage.gpd, "read_file", return_value=dataframe):
            metadata = await storage.DownloadStorageService.analyze_file(self.file(b"zip", "map.zip"))
        self.assertEqual(metadata, {
            "file_size_bytes": 3, "content_count": 2,
            "geometry_type": "Point", "bbox": "-75.0,10.0,-74.0,11.0",
        })


class DownloadUploadRouteTests(unittest.TestCase):
    def setUp(self):
        self.service = Mock()
        self.user = SimpleNamespace(id=uuid.uuid4(), is_active=True, role="USER")
        self.service.repository.get = AsyncMock(return_value=SimpleNamespace(layer_id=None, created_by=self.user.id))
        self.service.update_resource_metadata = AsyncMock()
        app = FastAPI()
        app.include_router(downloads.router, prefix="/downloads")
        app.dependency_overrides[downloads.get_db] = lambda: Mock()
        app.dependency_overrides[downloads.get_current_active_user] = lambda: self.user
        self.client = TestClient(app)
        self.url = f"/downloads/{uuid.uuid4()}/upload"

    def test_oversized_upload_returns_413_before_storage_or_metadata_write(self):
        with patch.object(downloads, "DownloadService", return_value=self.service), patch.object(
            storage, "MAX_FILE_SIZE", 4
        ), patch.object(storage.DownloadStorageService, "upload_resource_file", new_callable=AsyncMock) as upload:
            response = self.client.post(self.url, files={"file": ("data.csv", b"123456789", "text/csv")})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["detail"], "Archivo demasiado grande")
        upload.assert_not_awaited()
        self.service.update_resource_metadata.assert_not_awaited()

    def test_missing_filename_is_rejected_without_attribute_error(self):
        import asyncio

        with patch.object(downloads, "DownloadService", return_value=self.service):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(downloads.upload_resource_file(
                    uuid.uuid4(), UploadFile(file=io.BytesIO(b"abc")), Mock(), self.user
                ))
        self.assertEqual(caught.exception.status_code, 400)

    def test_successful_upload_receives_complete_file_and_saves_metadata(self):
        content = b"id\n1\n2\n"
        stored = {"file_url": "https://example.com/data.csv", "file_size_bytes": len(content)}

        async def upload(resource_id, file):
            self.assertEqual(await file.read(), content)
            return stored

        self.service.update_resource_metadata.return_value = {"saved": True}
        with patch.object(downloads, "DownloadService", return_value=self.service), patch.object(
            storage.DownloadStorageService, "upload_resource_file", side_effect=upload
        ):
            response = self.client.post(self.url, files={"file": ("data.csv", content, "text/csv")})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"saved": True})
        self.assertEqual(self.service.update_resource_metadata.call_args.args[1], {
            **stored, "content_count": 2,
        })


if __name__ == "__main__":
    unittest.main()
