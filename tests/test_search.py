"""Regresiones de búsqueda GIS tras retirar el módulo de proyectos."""

import unittest
from unittest.mock import AsyncMock, MagicMock

from app.services.search.service import SearchService


class SearchServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = AsyncMock()
        self.service = SearchService(self.db)

    def rows(self, rows):
        result = MagicMock()
        result.mappings.return_value.all.return_value = rows
        self.db.execute.return_value = result

    async def test_text_search_returns_gis_feature_with_navigation_metadata(self):
        self.rows([{
            "id": "feature-id", "layer_id": "layer-id",
            "display_name": "Parque", "properties": {"area": 12},
            "geometry": {"type": "Point", "coordinates": [-75, 10]},
            "bbox": [-75, 10, -75, 10],
        }])
        result = await self.service.search("Parque")
        feature = result["features"][0]
        self.assertEqual(result["type"], "FeatureCollection")
        self.assertEqual(feature["id"], "feature-id")
        self.assertEqual(feature["properties"]["source"], "feature")
        self.assertEqual(feature["properties"]["layer_id"], "layer-id")
        self.assertEqual(feature["properties"]["area"], 12)
        self.assertEqual(feature["geometry"]["coordinates"], [-75, 10])

    async def test_coordinate_search_preserves_distance_label(self):
        self.rows([{
            "id": "feature-id", "layer_id": "layer-id",
            "display_name": "Parque", "properties": None,
            "geometry": None, "bbox": None, "dist_metros": 1250,
        }])
        result = await self.service.search("10.42, -75.51")
        self.assertEqual(result["features"][0]["properties"]["distance_label"], "1.2 km")
        self.assertEqual(self.db.execute.call_args.args[1], {"lat": 10.42, "lon": -75.51, "public_only": False})

    async def test_empty_search_does_not_query_database(self):
        self.assertEqual(await self.service.search("  "), {"type": "FeatureCollection", "features": []})
        self.db.execute.assert_not_awaited()

    async def test_suggestions_are_unique_and_ignore_empty_names(self):
        result = MagicMock()
        result.scalars.return_value.all.return_value = ["Parque", None, "Parque", "Ruta"]
        self.db.execute.return_value = result
        self.assertEqual(await self.service.get_suggestions(2), ["Parque", "Ruta"])

    async def test_retired_project_view_cannot_update_historical_data(self):
        await self.service.log_view("historical-project-id", "project")
        self.db.execute.assert_not_awaited()
        self.db.commit.assert_not_awaited()

    async def test_feature_view_is_committed(self):
        await self.service.log_view(42, "feature")
        self.db.execute.assert_awaited_once()
        self.db.commit.assert_awaited_once()

    async def test_feature_view_integer_is_a_bound_sql_parameter(self):
        await self.service.log_view(42, "feature")
        statement = self.db.execute.call_args.args[0]
        self.assertIn("id", statement.compile().params)
        self.assertNotIn("uuid", str(statement))
        self.assertEqual(self.db.execute.call_args.args[1]["id"], 42)

    async def test_invalid_coordinates_do_not_query_database(self):
        for query in ("91, 10", "10, 181", "-91, -181"):
            with self.subTest(query=query), self.assertRaises(ValueError):
                await self.service.search(query)
        self.db.execute.assert_not_awaited()

    async def test_invalid_suggestion_limit_does_not_query_database(self):
        for limit in (0, -1, 51):
            with self.assertRaises(ValueError):
                await self.service.get_suggestions(limit)
        self.db.execute.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
