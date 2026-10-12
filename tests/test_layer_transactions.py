"""Unidad de trabajo de capas y compensación de archivos externos."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from backend_test_environment import configure_test_environment
configure_test_environment()

from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError
with patch("supabase.create_client"):
    from app.services.layers.service import LayerService
from app.repositories.layer_repository import LayerRepository


class LayerTransactionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = AsyncMock()
        self.service = LayerService(self.db)
        self.actor = SimpleNamespace(id=uuid.uuid4(), role="USER", is_active=True)
        self.layer = SimpleNamespace(id=uuid.uuid4(), created_by=self.actor.id, file_url="old-file")
        self.repository = SimpleNamespace(
            get=AsyncMock(return_value=self.layer), update=AsyncMock(return_value=self.layer),
            delete=AsyncMock(return_value=True), delete_features_by_layer_id=AsyncMock(),
            insert_features_bulk=AsyncMock(), create_layer=AsyncMock(return_value=self.layer),
        )
        self.service.repository = self.repository
        self.service._parse_file = AsyncMock(return_value={"type": "FeatureCollection", "features": []})
        self.service.geo_service.get_geometry_type = AsyncMock(return_value="Point")
        self.service.geo_service.process_geojson = AsyncMock(return_value=[{"properties": {}, "geom_wkt": "POINT(0 0)"}])
        self.file = SimpleNamespace(seek=AsyncMock())
        self.upload = patch("app.services.storage.storage_service.upload_file", new_callable=AsyncMock, return_value="new-file")
        self.cleanup = patch("app.services.storage.storage_service.delete_file", new_callable=AsyncMock, return_value=True)
        self.upload_mock = self.upload.start()
        self.cleanup_mock = self.cleanup.start()
        self.addCleanup(self.upload.stop)
        self.addCleanup(self.cleanup.stop)

    async def test_storage_failure_leaves_existing_geometries_untouched(self):
        self.upload_mock.side_effect = RuntimeError("upload failed")
        with self.assertRaisesRegex(RuntimeError, "upload failed"):
            await self.service.update_layer(self.layer.id, {}, self.file, actor=self.actor)
        self.repository.delete_features_by_layer_id.assert_not_awaited()
        self.repository.insert_features_bulk.assert_not_awaited()
        self.db.rollback.assert_awaited_once()
        self.cleanup_mock.assert_not_awaited()

    async def test_database_failure_rolls_back_and_removes_only_new_file(self):
        self.repository.insert_features_bulk.side_effect = SQLAlchemyError("insert failed")
        with self.assertRaises(SQLAlchemyError):
            await self.service.update_layer(self.layer.id, {}, self.file, actor=self.actor)
        self.repository.delete_features_by_layer_id.assert_awaited_once_with(self.layer.id, commit=False)
        self.db.rollback.assert_awaited_once()
        self.db.commit.assert_not_awaited()
        self.cleanup_mock.assert_awaited_once_with("new-file")

    async def test_success_commits_once_before_removing_old_file(self):
        events = []
        self.db.commit.side_effect = lambda: events.append("commit")
        self.cleanup_mock.side_effect = lambda url: events.append(url) or True
        await self.service.update_layer(self.layer.id, {}, self.file, actor=self.actor)
        self.db.commit.assert_awaited_once()
        self.repository.get.assert_awaited_once_with(self.layer.id, for_update=True)
        self.assertEqual(events, ["commit", "old-file"])
        self.repository.update.assert_awaited_once_with(self.layer, {"file_url": "new-file", "geometry_type": "Point"}, commit=False)

    async def test_refresh_failure_after_commit_does_not_remove_committed_file(self):
        self.db.refresh.side_effect = SQLAlchemyError("refresh failed")
        with self.assertRaises(SQLAlchemyError):
            await self.service.update_layer(self.layer.id, {}, self.file, actor=self.actor)
        self.db.commit.assert_awaited_once()
        self.cleanup_mock.assert_not_awaited()

    async def test_failed_database_delete_does_not_remove_existing_file(self):
        self.repository.delete.side_effect = SQLAlchemyError("delete failed")
        with self.assertRaises(SQLAlchemyError):
            await self.service.delete_layer(self.layer.id, actor=self.actor)
        self.cleanup_mock.assert_not_awaited()

    async def test_new_layer_feature_failure_does_not_leave_committed_partial_layer(self):
        self.service._normalize_layer_input = Mock(return_value=Mock())
        self.repository.insert_features_bulk.side_effect = SQLAlchemyError("insert failed")
        with self.assertLogs("app.services.layers.service", level="ERROR"), self.assertRaises(RuntimeError):
            await self.service.create_layer(Mock(), self.actor.id, self.file)
        self.assertFalse(self.repository.create_layer.call_args.kwargs["commit"])
        self.db.commit.assert_not_awaited()
        self.db.rollback.assert_awaited_once()
        self.cleanup_mock.assert_awaited_once_with("new-file")


class GeometryParameterTests(unittest.IsolatedAsyncioTestCase):
    async def test_layer_mutation_can_lock_and_refresh_existing_identity(self):
        db = AsyncMock()
        db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=None))
        await LayerRepository(db).get(uuid.uuid4(), for_update=True)
        statement = db.execute.call_args.args[0]
        self.assertIn("FOR UPDATE", str(statement.compile(dialect=postgresql.dialect())))
        self.assertTrue(statement.get_execution_options()["populate_existing"])

    async def test_geometry_wkt_is_bound_and_bulk_insert_can_defer_commit(self):
        db = AsyncMock()
        value = "POINT(0 0)'); DROP TABLE layers; --"
        await LayerRepository(db).insert_features_bulk(uuid.uuid4(), [{"properties": {}, "geom_wkt": value}], commit=False)
        compiled = db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
        self.assertNotIn(value, str(compiled))
        self.assertIn(value, compiled.params.values())
        db.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
