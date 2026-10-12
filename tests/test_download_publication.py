"""El catálogo público excluye recursos sin publicar y protege archivos al borrar."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from backend_test_environment import configure_test_environment
configure_test_environment()

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
with patch("supabase.create_client"):
    from app.api.v1 import downloads
from app.repositories.download_repository import DownloadRepository


class DownloadPublicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_route_requires_both_public_and_published(self):
        service = SimpleNamespace(get_downloads=AsyncMock(return_value=[]))
        with patch.object(downloads, "DownloadService", return_value=service):
            self.assertEqual(await downloads.list_public_downloads(Mock()), {})
        service.get_downloads.assert_awaited_once_with(show_in_public=True, is_published=True)

    async def test_repository_applies_publication_and_visibility_predicates(self):
        db = AsyncMock()
        db.execute.return_value = Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=[]))))
        await DownloadRepository(db).get_all(show_in_public=True, is_published=True)
        sql = str(db.execute.call_args.args[0])
        self.assertIn("show_in_public = true", sql)
        self.assertIn("is_published = true", sql)


class DownloadDeletionTests(unittest.TestCase):
    def setUp(self):
        self.actor = SimpleNamespace(id=uuid.uuid4(), role="USER", is_active=True)
        self.service = SimpleNamespace(
            repository=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(created_by=self.actor.id, file_path="file"))),
            delete_download=AsyncMock(return_value=True),
        )
        self.app = FastAPI()
        self.app.include_router(downloads.router, prefix="/resources")
        self.app.dependency_overrides[downloads.get_db] = lambda: Mock()
        self.app.dependency_overrides[downloads.get_current_active_user] = lambda: self.actor

    def test_database_failure_does_not_remove_physical_file(self):
        self.service.delete_download.side_effect = SQLAlchemyError("delete failed")
        with patch.object(downloads, "DownloadService", return_value=self.service), patch.object(
            downloads.DownloadStorageService, "delete_resource_files", new_callable=AsyncMock
        ) as cleanup, TestClient(self.app, raise_server_exceptions=False) as client:
            self.assertEqual(client.delete(f"/resources/{uuid.uuid4()}").status_code, 500)
        cleanup.assert_not_awaited()

    def test_cleanup_runs_after_confirmed_database_delete(self):
        events = []
        self.service.delete_download.side_effect = lambda identifier: events.append("database") or True
        with patch.object(downloads, "DownloadService", return_value=self.service), patch.object(
            downloads.DownloadStorageService, "delete_resource_files", new_callable=AsyncMock,
            side_effect=lambda *args: events.append("storage") or True,
        ), TestClient(self.app) as client:
            self.assertEqual(client.delete(f"/resources/{uuid.uuid4()}").status_code, 204)
        self.assertEqual(events, ["database", "storage"])


if __name__ == "__main__":
    unittest.main()
