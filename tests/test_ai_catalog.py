import unittest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from backend_test_environment import configure_test_environment

configure_test_environment()

from app.services.ia.tools.catalog import CatalogTools
from app.services.ia.tools import ToolsService
from app.services.ia.agent_service import AgentService
from app.services.ia.history_service import HistoryService


def result(rows=(), one=None):
    value = MagicMock()
    value.mappings.return_value.all.return_value = rows
    value.mappings.return_value.one_or_none.return_value = one
    return value


class CatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_unpublished_id_is_denied_before_feature_query(self):
        tools = CatalogTools(); tools.db = MagicMock(execute=AsyncMock(return_value=result()))
        response = await tools.consultar_registros_capa(str(uuid4()))
        self.assertFalse(response['success'])
        self.assertEqual(tools.db.execute.await_count, 1)
        self.assertIn("visibility = 'PUBLIC'", str(tools.db.execute.call_args.args[0]))

    async def test_exact_filter_is_bound_and_result_is_limited(self):
        layer_id = uuid4()
        tools = CatalogTools(); tools.db = MagicMock(execute=AsyncMock(side_effect=[
            result(one={'id': layer_id, 'name': 'RUTAS', 'source': 'Municipio', 'updated_at': '2026-10-14'}),
            result(rows=[{'id': i, 'properties': {'nombre': 'Ruta', 'extra': 'omitido'}} for i in range(51)])]))
        payload = "x' OR 1=1 --"
        response = await tools.consultar_registros_capa(str(layer_id), ['nombre'], 'nombre', payload, 500)
        statement, params = tools.db.execute.call_args.args
        self.assertNotIn(payload, str(statement))
        self.assertEqual(params['value'], payload)
        self.assertEqual(params['limit'], 51)
        self.assertEqual(len(response['data']), 50)
        self.assertTrue(response['has_more'])
        self.assertNotIn('extra', response['data'][0]['properties'])

    async def test_ambiguous_name_needs_id(self):
        tools = CatalogTools(); tools.db = MagicMock(execute=AsyncMock(return_value=result(rows=[{'id':uuid4(), 'name':'RUTAS'}]*2)))
        response = await tools.resolve_public_layer('RUTAS')
        self.assertEqual(response['code'], 'AMBIGUOUS_LAYER')

    async def test_agent_never_dispatches_denied_layer(self):
        agent = AgentService(MagicMock())
        agent.tools_service.resolve_public_layer = AsyncMock(return_value={'success':False, 'code':'LAYER_UNAVAILABLE'})
        agent.tools_service.consultar_datos_tabla = AsyncMock()
        self.assertFalse((await agent._execute_tool('consultar_datos_tabla', {'layer_name':'PRIVADA'}))['success'])
        agent.tools_service.consultar_datos_tabla.assert_not_awaited()

    async def test_named_zone_uses_known_geometry_instead_of_invented_coordinates(self):
        agent = AgentService(MagicMock())
        geometry={'type':'Polygon','coordinates':[[[-75,10],[-74,10],[-74,11],[-75,10]]]}
        agent._analysis_zones=[{'name':'Zona A','geometry':geometry}]
        agent.tools_service.resolve_public_layer=AsyncMock(return_value={'success':True,'layer':{'name':'RUTAS'}})
        agent.tools_service.analizar_capa_geografica=AsyncMock(return_value={'success':True,'analysis':{'total_features':3}})
        result=await agent._execute_tool('analizar_capa_geografica',{'layer_name':'RUTAS','zone_name':'Zona A'})
        self.assertEqual(agent.tools_service.analizar_capa_geografica.call_args.kwargs['zone_geometry'],geometry)
        self.assertEqual(result['analysis']['zone_name'],'Zona A')
        denied=await agent._execute_tool('analizar_capa_geografica',{'layer_name':'RUTAS','zone_name':'Inventada'})
        self.assertFalse(denied['success'])

    async def test_retrieval_has_permission_source_and_date(self):
        tools = CatalogTools(); tools.db = MagicMock(execute=AsyncMock(return_value=result(rows=[{
            'id':uuid4(), 'name':'RUTAS', 'description':'Red de rutas publicada', 'source':'Municipio', 'category':'Transporte', 'updated_at':'2026-10-14'}])))
        response = await tools.buscar_conocimiento_capas('rutas')
        self.assertIn("visibility = 'PUBLIC'", str(tools.db.execute.call_args.args[0]))
        self.assertEqual(response['sources'][0]['source'], 'Municipio')
        self.assertEqual(response['sources'][0]['updated_at'], '2026-10-14')

    async def test_search_service_is_public_only(self):
        self.assertTrue(ToolsService(MagicMock()).search_service.public_only)

    async def test_cadastral_query_never_labels_arbitrary_layers_as_predios(self):
        tools = ToolsService(MagicMock(execute=AsyncMock(return_value=result())))
        response = await tools.consultar_predios('Manga')
        query = str(tools.db.execute.call_args.args[0])
        self.assertIn("l.visibility = 'PUBLIC'",query)
        self.assertIn("LIKE '%predio%'",query)
        self.assertIn("LIKE '%catastr%'",query)
        self.assertEqual(response['map_actions'],[])

    async def test_map_ack_is_bound_to_owner_and_server_proposal(self):
        db = MagicMock(execute=AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=None))))
        service = HistoryService(db)
        service._get_redis = AsyncMock()
        self.assertFalse(await service.acknowledge_map_actions(uuid4(), uuid4(), 'request-1', [0]))
        query = str(db.execute.call_args.args[0])
        self.assertIn('c.user_id = :uid', query)
        self.assertIn("m.metadata->>'request_id' = :rid", query)
        service._get_redis.assert_not_called()


if __name__ == '__main__': unittest.main()
