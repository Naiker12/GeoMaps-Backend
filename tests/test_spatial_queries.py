"""Campos JSON parametrizados, extensiones válidas y errores observables."""

import re
import unittest
from unittest.mock import AsyncMock, Mock

from backend_test_environment import configure_test_environment
configure_test_environment()

from sqlalchemy.exc import SQLAlchemyError
from app.services.spatial.base_spatial import BaseSpatialAnalyzer


class SpatialQueryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = AsyncMock()
        self.analyzer = BaseSpatialAnalyzer(self.db)

    async def test_distribution_field_is_bound_instead_of_interpolated(self):
        field = "owner'); DROP TABLE layer_features; --"
        self.db.execute.side_effect = [Mock(scalar=Mock(return_value="layer")), Mock(fetchall=Mock(return_value=[("A", 2)]))]
        self.assertEqual(await self.analyzer.get_field_distribution("Layer", field), [{"name": "A", "value": 2}])
        statement, params = self.db.execute.call_args.args
        self.assertNotIn(field, str(statement))
        self.assertEqual(params["field"], field)
        self.assertIn("field", statement.compile().params)

    async def test_numeric_field_is_bound_and_signed_decimal_values_are_admitted(self):
        field = "area'unsafe"
        self.db.execute.side_effect = [Mock(scalar=Mock(return_value="layer")), Mock(fetchone=Mock(return_value=(2, -1.5, -3, 0, -3)))]
        result = await self.analyzer.get_numeric_stats("Layer", field)
        self.assertEqual(result["minimum"], -3)
        statement, params = self.db.execute.call_args.args
        self.assertNotIn(field, str(statement))
        self.assertEqual(params["field"], field)
        for value in ("-12", "0", ".5", "+2.3", "4e2", "-3.5E-1"):
            self.assertIsNotNone(re.fullmatch(params["number_pattern"], value))
        for value in ("12abc", "NaN", "Infinity", "--2", "3.4.5"):
            self.assertIsNone(re.fullmatch(params["number_pattern"], value))

    async def test_database_errors_roll_back_and_do_not_become_empty_results(self):
        failure = SQLAlchemyError("database unavailable")
        self.db.execute.side_effect = failure
        calls = [lambda: self.analyzer.query_features_in_bbox("Layer"),
                 lambda: self.analyzer.count_features_in_bbox("Layer"),
                 lambda: self.analyzer.get_field_distribution("Layer", "field"),
                 lambda: self.analyzer.get_numeric_stats("Layer", "field"),
                 lambda: self.analyzer.get_available_layers_in_bbox()]
        for call in calls:
            with self.assertLogs("app.services.spatial.base_spatial", level="ERROR"), self.assertRaises(SQLAlchemyError) as caught:
                await call()
            self.assertIs(caught.exception, failure)
        self.assertEqual(self.db.rollback.await_count, len(calls))

    async def test_invalid_limits_do_not_query_database(self):
        for limit in (0, -1, 501, True):
            with self.assertRaises(ValueError):
                await self.analyzer.query_features_in_bbox("Layer", limit)
            with self.assertRaises(ValueError):
                await self.analyzer.get_field_distribution("Layer", "field", limit)
        self.db.execute.assert_not_awaited()

    def test_bbox_requires_finite_ordered_geographic_coordinates(self):
        for bbox in ({}, {"xmin": 0}, {"xmin": 2, "ymin": 0, "xmax": 1, "ymax": 1},
                     {"xmin": 0, "ymin": 0, "xmax": float("inf"), "ymax": 1},
                     {"xmin": -181, "ymin": 0, "xmax": 1, "ymax": 1}):
            with self.assertRaises(ValueError):
                BaseSpatialAnalyzer(self.db, bbox)
        source = {"xmin": "-75", "ymin": 10, "xmax": -74, "ymax": 11, "lim": 99999}
        analyzer = BaseSpatialAnalyzer(self.db, source)
        self.assertEqual(analyzer.bbox, {"xmin": -75.0, "ymin": 10.0, "xmax": -74.0, "ymax": 11.0})


if __name__ == "__main__":
    unittest.main()
