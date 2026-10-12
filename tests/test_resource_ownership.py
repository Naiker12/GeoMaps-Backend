"""Permisos de escritura comprobados antes de modificar DB o storage."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from backend_test_environment import configure_test_environment
configure_test_environment()

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.core.security.ownership import ensure_resource_owner
with patch("supabase.create_client"):
    from app.services.layers.service import LayerService
    from app.api.v1 import layers as routes
    from app.api.v1 import downloads


class OwnershipPolicyTests(unittest.TestCase):
    def test_only_owner_or_active_administrator_can_manage_resource(self):
        owner = uuid.uuid4()
        ensure_resource_owner(SimpleNamespace(id=owner, role="USER", is_active=True), owner)
        for role in ("ADMIN", "SUPER_ADMIN"):
            ensure_resource_owner(SimpleNamespace(id=uuid.uuid4(), role=role, is_active=True), None)
        for actor, owner_id in (
            (SimpleNamespace(id=uuid.uuid4(), role="USER", is_active=True), owner),
            (SimpleNamespace(id=owner, role="USER", is_active=True), None),
            (SimpleNamespace(id=owner, role="SUPER_ADMIN", is_active=False), owner),
        ):
            with self.assertRaises(PermissionError):
                ensure_resource_owner(actor, owner_id)


class LayerMutationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = LayerService(AsyncMock())
        self.layer = SimpleNamespace(id=uuid.uuid4(), created_by=uuid.uuid4(), file_url="https://example.com/file")
        self.actor = SimpleNamespace(id=uuid.uuid4(), role="USER", is_active=True)
        self.repository = SimpleNamespace(get=AsyncMock(return_value=self.layer), update=AsyncMock(return_value=self.layer), delete=AsyncMock(return_value=True))
        self.service.repository = self.repository

    async def test_foreign_layer_update_does_not_parse_or_write(self):
        with patch.object(self.service, "_parse_file", new_callable=AsyncMock) as parse:
            with self.assertRaises(PermissionError):
                await self.service.update_layer(self.layer.id, {"name": "changed"}, file=Mock(), actor=self.actor)
        parse.assert_not_awaited()
        self.repository.update.assert_not_awaited()

    async def test_foreign_layer_delete_does_not_remove_storage(self):
        with patch("app.services.storage.storage_service.delete_file", new_callable=AsyncMock) as delete:
            with self.assertRaises(PermissionError):
                await self.service.delete_layer(self.layer.id, actor=self.actor)
        delete.assert_not_awaited()
        self.repository.delete.assert_not_awaited()

    async def test_owner_and_admin_updates_are_admitted(self):
        for actor in (SimpleNamespace(id=self.layer.created_by, role="USER", is_active=True),
                      SimpleNamespace(id=uuid.uuid4(), role="ADMIN", is_active=True)):
            self.assertIs(await self.service.update_layer(self.layer.id, {"name": "changed"}, actor=actor), self.layer)
        self.assertEqual(self.repository.update.await_count, 2)


class MutationRouteTests(unittest.TestCase):
    def test_layer_delete_translates_denial_and_missing_resource(self):
        app = FastAPI()
        app.include_router(routes.router, prefix="/layers")
        app.dependency_overrides[routes.get_db] = lambda: Mock()
        app.dependency_overrides[routes.get_current_active_user] = lambda: SimpleNamespace(id=uuid.uuid4())
        service = SimpleNamespace(delete_layer=AsyncMock(side_effect=PermissionError("denied")))
        with patch.object(routes, "LayerService", return_value=service), TestClient(app) as client:
            self.assertEqual(client.delete(f"/layers/{uuid.uuid4()}").status_code, 403)
            service.delete_layer.side_effect = None
            service.delete_layer.return_value = False
            self.assertEqual(client.delete(f"/layers/{uuid.uuid4()}").status_code, 404)

    def test_foreign_download_cannot_be_uploaded_or_deleted(self):
        app = FastAPI()
        app.include_router(downloads.router, prefix="/resources")
        actor = SimpleNamespace(id=uuid.uuid4(), role="USER", is_active=True)
        app.dependency_overrides[downloads.get_db] = lambda: Mock()
        app.dependency_overrides[downloads.get_current_active_user] = lambda: actor
        service = SimpleNamespace(repository=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(created_by=uuid.uuid4()))), delete_download=AsyncMock())
        with patch.object(downloads, "DownloadService", return_value=service), patch.object(
            downloads.DownloadStorageService, "delete_resource_files", new_callable=AsyncMock
        ) as delete, TestClient(app) as client:
            self.assertEqual(client.delete(f"/resources/{uuid.uuid4()}").status_code, 403)
            response = client.post(f"/resources/{uuid.uuid4()}/upload", files={"file": ("data.csv", b"id\n1\n", "text/csv")})
            self.assertEqual(response.status_code, 403)
        delete.assert_not_awaited()
        service.delete_download.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
