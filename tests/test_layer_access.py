"""Privacidad de lecturas GIS y observabilidad de errores de persistencia."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from backend_test_environment import configure_test_environment
configure_test_environment()

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
with patch("supabase.create_client"):
    from app.api.v1 import layers as routes
from app.repositories.layer_repository import LayerRepository


class LayerAccessRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(routes.router, prefix="/layers")
        self.app.dependency_overrides[routes.get_db] = lambda: Mock()
        self.service = SimpleNamespace(
            get_categories=AsyncMock(return_value=[]), get_categories_tree=AsyncMock(return_value=[]),
            get_features_properties=AsyncMock(return_value=[]), get_feature_by_id=AsyncMock(return_value={"id": "42"}),
            get_field_values=AsyncMock(return_value={}), get_field_stats=AsyncMock(return_value={}),
            get_layer_geojson=AsyncMock(return_value={"type": "FeatureCollection", "features": []}),
        )

    def test_read_routes_forward_public_policy_for_anonymous_and_authenticated_users(self):
        layer_id = uuid.uuid4()
        paths = [
            ("/categories", "get_categories"), ("/categories/tree", "get_categories_tree"),
            (f"/features/properties?layer_ids={layer_id}", "get_features_properties"),
            ("/features/42", "get_feature_by_id"),
            (f"/{layer_id}/field-values?field=name", "get_field_values"),
            (f"/{layer_id}/field-stats?field=area", "get_field_stats"),
            (f"/{layer_id}/features", "get_layer_geojson"),
        ]
        for user in (None, SimpleNamespace(is_active=True)):
            self.app.dependency_overrides[routes.get_current_user_optional] = lambda: user
            with patch.object(routes, "LayerService", return_value=self.service), TestClient(self.app) as client:
                for path, method in paths:
                    with self.subTest(path=path, authenticated=user is not None):
                        self.assertEqual(client.get(f"/layers{path}").status_code, 200)
                        self.assertEqual(getattr(self.service, method).call_args.kwargs["public_only"], user is None)

    def test_inaccessible_feature_is_404(self):
        self.app.dependency_overrides[routes.get_current_user_optional] = lambda: None
        self.service.get_feature_by_id.return_value = None
        with patch.object(routes, "LayerService", return_value=self.service), TestClient(self.app) as client:
            self.assertEqual(client.get("/layers/features/42").status_code, 404)


class LayerAccessRepositoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = AsyncMock()
        result = Mock()
        result.scalars.return_value.all.return_value = []
        result.mappings.return_value.all.return_value = []
        result.mappings.return_value.first.return_value = None
        result.all.return_value = []
        result.fetchall.return_value = []
        result.fetchone.return_value = None
        self.db.execute.return_value = result
        self.repository = LayerRepository(self.db)

    async def test_public_filter_is_part_of_every_orm_read(self):
        layer_id = uuid.uuid4()
        calls = [
            lambda: self.repository.get_unique_categories(public_only=True),
            lambda: self.repository.get_categories_tree(public_only=True),
            lambda: self.repository.get_features_as_geojson(layer_id, public_only=True),
            lambda: self.repository.get_features_properties([layer_id], public_only=True),
            lambda: self.repository.get_feature_by_id(42, public_only=True),
        ]
        for call in calls:
            await call()
            compiled = self.db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
            self.assertIn("PUBLIC", compiled.params.values())
            self.assertIn("layers.visibility =", str(compiled))

    async def test_field_statistics_and_values_bind_public_access(self):
        layer_id = uuid.uuid4()
        for method in (self.repository.get_field_values, self.repository.get_field_stats):
            await method(layer_id, "area", public_only=True)
            self.assertTrue(self.db.execute.call_args.args[1]["public_only"])
            self.assertIn("l.visibility = 'PUBLIC'", str(self.db.execute.call_args.args[0]))

    async def test_database_errors_are_not_reported_as_missing_features(self):
        self.db.execute.side_effect = RuntimeError("database unavailable")
        with self.assertRaisesRegex(RuntimeError, "database unavailable"):
            await self.repository.get_feature_by_id(42)

    async def test_non_integer_feature_identifiers_do_not_query_database(self):
        for identifier in (uuid.uuid4(), 1.5, True):
            self.assertIsNone(await self.repository.get_feature_by_id(identifier))
        self.db.execute.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
