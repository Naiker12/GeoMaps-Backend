"""Contexto GIS real, consultas verificables y presentación de análisis IA."""

import json
import unittest
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from backend_test_environment import configure_test_environment
configure_test_environment()

from app.services.ia.geo_context import normalize_extent_to_bbox, resolve_geo_context
from app.services.ia.tools.geographic_analysis import GeographicAnalysisTools
with patch("supabase.create_client"):
    from app.services.ia.agent_service import AgentService
from app.schemas.ia import ChatRequest, IAModelConfig


class GeographicContextTests(unittest.TestCase):
    def test_web_mercator_is_transformed_with_longitude_latitude_order(self):
        bbox = normalize_extent_to_bbox({"xmin": 0, "ymin": 0, "xmax": 111319.490793, "ymax": 111325.142866,
                                         "spatialReference": {"wkid": 102100}})
        for actual, expected in zip(bbox, [0, 0, 1, 1]):
            self.assertAlmostEqual(actual, expected, places=6)

    def test_conversation_zone_takes_precedence_over_viewport(self):
        result = resolve_geo_context({"extent": [0, 0, 1, 1]}, {"conversation_zone": {"bbox": [2, 2, 3, 3]}})
        self.assertEqual(result["bbox"], [2, 2, 3, 3])

    def test_unsupported_crs_and_partial_extent_are_rejected(self):
        for extent in ({"xmin": 0}, {"xmin": 0, "ymin": 0, "xmax": 1, "ymax": 1, "spatialReference": {"wkid": 3116}}, [0, 0, 1, 1, 2]):
            with self.assertRaises(ValueError):
                normalize_extent_to_bbox(extent)
        self.assertIsNone(normalize_extent_to_bbox({}))


class GeographicToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tool = GeographicAnalysisTools()
        self.tool.db = AsyncMock()
        self.layer_id = uuid.uuid4()

    def result(self, rows):
        return Mock(mappings=Mock(return_value=Mock(all=Mock(return_value=rows))))

    def rows(self, rows):
        self.tool.db.execute.side_effect = [self.result([{"id": self.layer_id, "name": "Parques"}]), self.result(rows)]

    async def test_exact_bbox_and_area_units_are_preserved_with_provenance(self):
        self.rows([{"geometry_type": "ST_Polygon", "count": 3, "area_m2": Decimal("125.5")}])
        result = await self.tool.analizar_capa_geografica("Parques", bbox=[-75, 10, -74, 11])
        self.assertEqual(result["analysis"]["total_features"], 3)
        self.assertEqual(result["analysis"]["sum_feature_area_m2"], 125.5)
        self.assertEqual(result["analysis"]["scope"], "bbox")
        self.assertEqual(result["analytics_data"]["data"], [{"name": "Polygon", "value": 3}])
        sql, params = self.tool.db.execute.call_args.args
        self.assertIn("ST_Intersects", str(sql))
        self.assertIn("ST_Area(geom::geography)", str(sql))
        self.assertIn("ST_IsValid", str(sql))
        self.assertEqual(params["xmin"], -75)

    async def test_radius_is_bound_in_meters_and_zero_does_not_create_empty_chart(self):
        self.rows([])
        result = await self.tool.analizar_capa_geografica("Parques", coordinates=[-75, 10], radius_m=500)
        sql, params = self.tool.db.execute.call_args.args
        self.assertIn("ST_DWithin", str(sql))
        self.assertEqual(params["radius_m"], 500)
        self.assertEqual(result["analysis"]["scope"], "radius")
        self.assertEqual(result["data"]["total_features"], 0)
        self.assertIsNone(result["analytics_data"])

    async def test_ambiguous_layer_does_not_execute_analysis(self):
        self.tool.db.execute.return_value = self.result([{"id": uuid.uuid4(), "name": "Parques Norte"}, {"id": uuid.uuid4(), "name": "Parques Sur"}])
        result = await self.tool.analizar_capa_geografica("Parques")
        self.assertTrue(result["needs_clarification"])
        self.assertEqual(len(result["candidates"]), 2)
        self.assertEqual(self.tool.db.execute.await_count, 1)

    async def test_invalid_point_or_partial_radius_does_not_query_database(self):
        for args in ({"coordinates": [-75, 10]}, {"coordinates": [-75, 91], "radius_m": 100}, {"coordinates": [-75, 10], "radius_m": 50001}):
            with self.assertRaises(ValueError):
                await self.tool.analizar_capa_geografica("Parques", **args)
        self.tool.db.execute.assert_not_awaited()

    async def test_explicit_layer_id_resolves_same_named_layers(self):
        self.rows([])
        await self.tool.analizar_capa_geografica("Parques", layer_id=str(self.layer_id))
        _, params = self.tool.db.execute.call_args_list[0].args
        self.assertEqual(params["requested_layer_id"], self.layer_id)

    async def test_polygon_is_bound_and_intersected_exactly(self):
        self.rows([])
        polygon = {"type": "Polygon", "coordinates": [[[-75, 10], [-74, 10], [-74, 11], [-75, 10]]]}
        result = await self.tool.analizar_capa_geografica("Parques", zone_geometry=polygon)
        sql, params = self.tool.db.execute.call_args.args
        self.assertIn("ST_GeomFromGeoJSON(:zone_geometry)", str(sql))
        self.assertEqual(json.loads(params["zone_geometry"]), polygon)
        self.assertEqual(result["analysis"]["scope"], "zone_polygon")

    async def test_self_crossing_polygon_is_rejected_before_query(self):
        polygon = {"type": "Polygon", "coordinates": [[[-75, 10], [-74, 11], [-75, 11], [-74, 10], [-75, 10]]]}
        with self.assertRaises(ValueError):
            await self.tool.analizar_capa_geografica("Parques", zone_geometry=polygon)
        self.tool.db.execute.assert_not_awaited()


class AgentGeographyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.agent = AgentService(AsyncMock())
        self.agent._analysis_bbox = [-75, 10, -74, 11]
        self.agent.tools_service.resolve_public_layer = AsyncMock(side_effect=lambda name, layer_id=None: {"success": True, "layer": {"id": uuid.uuid4(), "name": name}})

    async def test_foreign_conversation_creates_owned_history(self):
        user = SimpleNamespace(id=uuid.uuid4())
        request = ChatRequest(message="Analiza", conversation_id=uuid.uuid4())
        self.agent.db.execute.return_value = Mock(fetchone=Mock(return_value=None))
        new_id = uuid.uuid4()
        self.agent.history_service.create_conversation = AsyncMock(return_value=new_id)
        result = await self.agent._get_or_create_conversation(request, user, IAModelConfig(name="Test", provider="gemini", model_id="test"))
        self.assertEqual(result, new_id)
        _, params = self.agent.db.execute.call_args.args
        self.assertEqual(params["uid"], user.id)
        self.agent.history_service.create_conversation.assert_awaited_once()

    async def test_dispatch_inherits_extent_but_does_not_restrict_explicit_global_scope(self):
        with patch.object(self.agent.tools_service, "analizar_capa_geografica", new_callable=AsyncMock, return_value={"success": True}) as tool:
            await self.agent._execute_tool("analizar_capa_geografica", {"layer_name": "Parques"})
            self.assertEqual(tool.call_args.kwargs["bbox"], self.agent._analysis_bbox)
            await self.agent._execute_tool("analizar_capa_geografica", {"layer_name": "Parques", "scope": "entire_layer"})
            self.assertNotIn("bbox", tool.call_args.kwargs)

    async def test_selected_polygon_replaces_viewport_and_radius_keeps_own_scope(self):
        self.agent._analysis_zone_geometry = {"type": "Polygon", "coordinates": []}
        with patch.object(self.agent.tools_service, "analizar_capa_geografica", new_callable=AsyncMock, return_value={"success": True}) as tool:
            await self.agent._execute_tool("analizar_capa_geografica", {"layer_name": "Parques"})
            self.assertEqual(tool.call_args.kwargs["zone_geometry"], self.agent._analysis_zone_geometry)
            self.assertNotIn("bbox", tool.call_args.kwargs)
            await self.agent._execute_tool("analizar_capa_geografica", {"layer_name": "Parques", "coordinates": [-75, 10], "radius_m": 100})
            self.assertNotIn("zone_geometry", tool.call_args.kwargs)
            self.assertNotIn("bbox", tool.call_args.kwargs)

    async def test_chat_selects_chart_without_preliminary_questions_and_keeps_all_analysis(self):
        config = IAModelConfig(name="Test", provider="gemini", model_id="test")
        self.agent._get_model_config = AsyncMock(return_value=config)
        self.agent._try_fast_zone_comparison = AsyncMock(return_value=None)
        self.agent._get_available_layers = AsyncMock(return_value=[])
        self.agent._save_audit_log = AsyncMock()
        self.agent.history_service = SimpleNamespace(create_conversation=AsyncMock(return_value=uuid.uuid4()),
            get_trimmed_history=AsyncMock(return_value=[]), get_conversation_summary=AsyncMock(return_value=None), save_message=AsyncMock())
        self.agent.tools_service.get_tools_metadata = AsyncMock(return_value=[{"type":"function", "function":{"name":"analizar_capa_geografica"}}])
        self.agent.tools_service.analizar_capa_geografica = AsyncMock(side_effect=[
            {"success": True, "analysis": {"total_features": 3}},
            {"success": True, "analysis": {"total_features": 7}},
        ])
        calls = [{"id": str(index), "type": "function", "function": {"name": "analizar_capa_geografica", "arguments": json.dumps({"layer_name": name})}}
                 for index, name in enumerate(("Parques", "Rutas"))]
        client = SimpleNamespace(chat_complete=AsyncMock(side_effect=[
            {"message": {"role": "assistant", "content": "", "tool_calls": calls}},
            {"message": {"role": "assistant", "content": "Análisis listo"}},
        ]))
        with patch("app.services.ia.agent_service.LLMProviderFactory.create", return_value=client):
            response = await self.agent.chat(ChatRequest(message="Grafica estas capas"), SimpleNamespace(id=uuid.uuid4(), full_name="User", email="user@example.com"))
        self.assertEqual(client.chat_complete.await_count, 2)
        self.assertEqual(response.analysis_results, [{"total_features": 3}, {"total_features": 7}])
        self.assertEqual(response.message, "Análisis listo")


if __name__ == "__main__":
    unittest.main()
