"""Permisos de búsqueda HTTP y SQL portable sobre SQLite en memoria."""

import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from backend_test_environment import configure_test_environment
configure_test_environment()

from fastapi import FastAPI
from fastapi.testclient import TestClient
with patch("supabase.create_client"):
    from app.api.v1 import search as routes
from app.services.search.service import SearchService


class SearchAccessRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(routes.router, prefix="/search")
        self.app.dependency_overrides[routes.get_db] = lambda: Mock()
        self.service = SimpleNamespace(
            search=AsyncMock(return_value={"type": "FeatureCollection", "features": []}),
            get_suggestions=AsyncMock(return_value=[]), log_view=AsyncMock(),
        )

    def test_anonymous_routes_request_public_only_and_authenticated_routes_preserve_access(self):
        for user in (None, SimpleNamespace(id="user", is_active=True)):
            self.app.dependency_overrides[routes.get_current_user_optional] = lambda: user
            with patch.object(routes, "SearchService", return_value=self.service) as service:
                with TestClient(self.app) as client:
                    self.assertEqual(client.get("/search/?q=Parque").status_code, 200)
                    self.assertEqual(client.get("/search/suggestions").status_code, 200)
                    self.assertEqual(client.post("/search/viewed?id=42&source=feature").status_code, 200)
                self.assertEqual(service.call_count, 3)
                self.assertTrue(all(call.kwargs["public_only"] == (user is None) for call in service.call_args_list))
        self.service.log_view.assert_awaited_with(42, "feature")

    def test_invalid_feature_identifiers_are_rejected_before_writing(self):
        self.app.dependency_overrides[routes.get_current_user_optional] = lambda: None
        with TestClient(self.app) as client:
            for identifier in ("uuid", "0", "-1", "1.5"):
                self.assertEqual(client.post(f"/search/viewed?id={identifier}&source=feature").status_code, 422)
        self.service.log_view.assert_not_awaited()


class SearchAccessSQLTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.create_function("NOW", 0, lambda: "2026-10-11T00:00:00Z")
        self.connection.executescript("""
            CREATE TABLE layers (id TEXT PRIMARY KEY, visibility TEXT);
            CREATE TABLE layer_features (id INTEGER PRIMARY KEY, layer_id TEXT, display_name TEXT, last_viewed_at TEXT);
            INSERT INTO layers VALUES ('public', 'PUBLIC'), ('private', 'PRIVATE'), ('team', 'TEAM');
            INSERT INTO layer_features VALUES (1, 'public', 'Parque', NULL), (2, 'private', 'Secreto', NULL), (3, 'team', 'Equipo', NULL);
        """)

        async def execute(statement, params):
            rows = self.connection.execute(str(statement), params).fetchall()
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [row[0] for row in rows]))

        self.db = SimpleNamespace(execute=execute, commit=AsyncMock())

    async def test_public_suggestions_exclude_private_and_team_names(self):
        self.assertEqual(await SearchService(self.db, public_only=True).get_suggestions(50), ["Parque"])
        self.assertEqual(set(await SearchService(self.db).get_suggestions(50)), {"Parque", "Secreto", "Equipo"})

    async def test_public_view_cannot_update_private_feature(self):
        service = SearchService(self.db, public_only=True)
        await service.log_view(1, "feature")
        await service.log_view(2, "feature")
        rows = dict(self.connection.execute("SELECT id, last_viewed_at FROM layer_features"))
        self.assertIsNotNone(rows[1])
        self.assertIsNone(rows[2])
        await SearchService(self.db).log_view(2, "feature")
        self.assertIsNotNone(self.connection.execute("SELECT last_viewed_at FROM layer_features WHERE id=2").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
