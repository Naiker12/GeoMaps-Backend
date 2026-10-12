"""Regresiones de almacenamiento sin llamadas a Supabase."""

import importlib
import io
import threading
import unittest
from unittest.mock import Mock, patch

from backend_test_environment import configure_test_environment

configure_test_environment()

from fastapi import UploadFile

# Evitar crear un cliente externo al importar el singleton del módulo.
with patch("supabase.create_client"):
    storage = importlib.import_module("app.services.storage.service")


class StorageServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = Mock()
        with patch("supabase.create_client", return_value=self.client):
            self.service = storage.StorageService()
        self.bucket = self.client.storage.from_.return_value

    async def test_upload_preserves_metadata_and_uses_worker_thread(self):
        event_loop_thread = threading.get_ident()
        worker_threads = []

        def upload(**kwargs):
            worker_threads.append(threading.get_ident())
            self.assertEqual(kwargs["file"], b"abc")
            return Mock(error=None)

        self.bucket.upload.side_effect = upload
        self.bucket.get_public_url.return_value = "https://example.com/file.csv?download=1"
        file = UploadFile(file=io.BytesIO(b"abc"), filename="datos.csv")
        info = await self.service.upload_file_to_bucket(file, "Download", "resources/test/")
        self.assertEqual(info.file_size_bytes, 3)
        self.assertEqual(info.mime_type, "text/csv")
        self.assertEqual(info.extension, ".csv")
        self.assertEqual(info.public_url, "https://example.com/file.csv")
        self.assertTrue(info.path.startswith("resources/test/"))
        self.assertNotEqual(worker_threads[0], event_loop_thread)

    async def test_oversized_upload_reads_only_limit_plus_one_and_never_uploads(self):
        stream = io.BytesIO(b"123456789")
        file = UploadFile(file=stream, filename="datos.csv")
        with patch.object(storage, "MAX_FILE_SIZE", 4):
            with self.assertRaisesRegex(ValueError, "Archivo demasiado grande"):
                await self.service.upload_file_to_bucket(file, "Download")
        self.assertEqual(stream.tell(), 5)
        self.bucket.upload.assert_not_called()

    async def test_upload_at_size_limit_is_accepted(self):
        self.bucket.upload.return_value = Mock(error=None)
        self.bucket.get_public_url.return_value = "https://example.com/file"
        with patch.object(storage, "MAX_FILE_SIZE", 3):
            info = await self.service.upload_file_to_bucket(
                UploadFile(file=io.BytesIO(b"abc"), filename="file"), "Download"
            )
        self.assertEqual(info.file_size_bytes, 3)

    async def test_storage_operations_run_outside_event_loop(self):
        event_loop_thread = threading.get_ident()
        worker_threads = []

        def result(value):
            def call(*args):
                worker_threads.append(threading.get_ident())
                return value
            return call

        self.bucket.create_signed_url.side_effect = result({"signedURL": "/signed/file"})
        self.bucket.remove.side_effect = result([{"name": "file"}])
        self.bucket.download.side_effect = result(b"data")
        self.assertEqual(
            await self.service.create_signed_url("Download", "file"),
            "https://example.supabase.co/signed/file",
        )
        self.assertTrue(await self.service.delete_file_by_path("Download", "file"))
        self.assertEqual(await self.service.download_file_by_path("Download", "file"), b"data")
        self.assertEqual(len(worker_threads), 3)
        self.assertTrue(all(thread != event_loop_thread for thread in worker_threads))

    async def test_upload_failure_preserves_original_cause(self):
        failure = OSError("storage unavailable")
        self.bucket.upload.side_effect = failure
        with self.assertRaises(RuntimeError) as caught:
            await self.service.upload_file_to_bucket(
                UploadFile(file=io.BytesIO(b"abc"), filename="file"), "Download"
            )
        self.assertIs(caught.exception.__cause__, failure)


if __name__ == "__main__":
    unittest.main()
