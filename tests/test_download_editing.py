"""Editing resources preserves optional fields and enforces ownership."""
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from backend_test_environment import configure_test_environment
configure_test_environment()
from fastapi import FastAPI
from fastapi.testclient import TestClient
with patch("supabase.create_client"):
    from app.api.v1 import downloads

class DownloadEditingTests(unittest.TestCase):
    def setUp(self):
        self.actor = SimpleNamespace(id=uuid.uuid4(), role="USER", is_active=True)
        self.resource = SimpleNamespace(
            id=uuid.uuid4(), created_by=self.actor.id, name="Manual", category="Guías",
            description="Descripción del recurso", tags=[], metadata_={},
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        )
        self.service = SimpleNamespace(repository=SimpleNamespace(get=AsyncMock(return_value=self.resource), update=AsyncMock(return_value=self.resource)),create_download=AsyncMock(return_value=self.resource))
        self.app = FastAPI()
        self.app.include_router(downloads.router, prefix="/resources")
        self.app.dependency_overrides[downloads.get_db] = lambda: Mock()
        self.app.dependency_overrides[downloads.get_current_active_user] = lambda: self.actor

    def request(self, values):
        with patch.object(downloads, "DownloadService", return_value=self.service), TestClient(self.app, raise_server_exceptions=False) as client:
            return client.patch(f"/resources/{uuid.uuid4()}", data=values)

    def test_partial_edit_only_updates_supplied_fields(self):
        self.assertEqual(self.request({"name":"Nuevo nombre","tags":'["Oficial"]',"is_published":"false"}).status_code, 200)
        self.service.repository.update.assert_awaited_once_with(self.resource,{"name":"Nuevo nombre","tags":["Oficial"],"is_published":False})

    def test_manual_mode_explicitly_removes_layer_link(self):
        self.assertEqual(self.request({"layer_id":"manual"}).status_code, 200)
        self.assertIsNone(self.service.repository.update.call_args.args[1]["layer_id"])

    def test_invalid_tags_do_not_reach_database(self):
        self.assertEqual(self.request({"tags":"invalid"}).status_code,422)
        self.service.repository.update.assert_not_awaited()

    def test_foreign_resource_is_not_editable(self):
        self.resource.created_by=uuid.uuid4()
        self.assertEqual(self.request({"name":"Intrusión"}).status_code,403)
        self.service.repository.update.assert_not_awaited()

    def test_missing_resource_returns_not_found(self):
        self.service.repository.get.return_value=None
        self.assertEqual(self.request({"name":"Nuevo"}).status_code,404)
        self.service.repository.update.assert_not_awaited()

    def test_create_keeps_tags(self):
        with patch.object(downloads,"DownloadService",return_value=self.service), TestClient(self.app,raise_server_exceptions=False) as client:
            self.assertEqual(client.post("/resources/",data={"name":"Manual","category":"Guías","tags":'["Oficial"]'}).status_code,201)
        self.assertEqual(self.service.create_download.call_args.args[0].tags,["Oficial"])

if __name__=="__main__":unittest.main()
