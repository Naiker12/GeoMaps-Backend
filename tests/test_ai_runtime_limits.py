import json
import unittest
from app.services.ia.runtime_limits import coherent_history, bounded_tool_result, validate_native_calls
from app.services.ia.tools.query_scope import query_scope
from app.services.ia.provider_connections import reported_capabilities
from app.services.ia.geo_context import resolve_geo_context
from app.services.ia.agent_service import allows_map_changes
from app.services.ia.comparison_results import build_zone_comparison


class RuntimeTests(unittest.TestCase):
    def test_unknown_model_capabilities_are_not_invented(self):
        capabilities = reported_capabilities({'id':'unknown'})
        self.assertIsNone(capabilities['has_function_calling'])
        self.assertEqual(capabilities['capability_source'],'not_reported')

    def test_provider_catalog_reports_tools_vision_and_context(self):
        capabilities = reported_capabilities({'supported_parameters':['tools','response_format'], 'context_length':128000, 'architecture':{'input_modalities':['text','image']}})
        self.assertTrue(capabilities['has_function_calling'])
        self.assertTrue(capabilities['has_vision'])
        self.assertEqual(capabilities['max_context_tokens'],128000)

    def test_disabled_unknown_duplicate_and_non_object_calls_are_denied(self):
        tools = [{'function':{'name':'catalog'}}]
        call = {'id':'a','function':{'name':'catalog','arguments':'{}'}}
        for calls, enabled in (([call],[]),([call,call],tools),([dict(call,function={'name':'catalog','arguments':'[]'})],tools)):
            with self.assertRaises(ValueError): validate_native_calls(calls,enabled)

    def test_scope_uses_exact_bound_filter_and_spatial_intersection(self):
        sql, params, bbox = query_scope([-75,10,-74,11], 'nombre', "x' OR true --")
        self.assertIn('ST_Intersects',sql)
        self.assertIn('ST_IsValid',sql)
        self.assertNotIn("x' OR true",sql)
        self.assertEqual(params['filter_value'],"x' OR true --")
        self.assertEqual(bbox,[-75,10,-74,11])

    def test_invalid_scope_fails_before_query(self):
        with self.assertRaises(ValueError): query_scope([-75,91,-74,92])
        with self.assertRaises(ValueError): query_scope(filter_field='nombre')

    def test_cleared_live_filter_overrides_historical_filter(self):
        geo = resolve_geo_context({'active_filter':None}, {'applied_filters':[{'filter':"ruta='old'"}]})
        self.assertEqual(geo['applied_filters'],[])
        geo = resolve_geo_context({'active_filter':{'key':'ruta','value':'new'}}, {})
        self.assertEqual(geo['applied_filters'],[{'key':'ruta','value':'new'}])

    def test_explicit_no_map_change_request_is_respected(self):
        for request in ('No cambies el mapa, solo consulta los datos','Analiza rutas sin modificar el mapa','No actives capas ni cambies el mapa'):
            self.assertFalse(allows_map_changes(request))
        self.assertTrue(allows_map_changes('Activa la capa RUTAS'))

    def test_comparison_only_uses_complete_known_polygon_results(self):
        analyses=[{'zone_name':name,'scope':'zone_polygon','count_is_complete':True,'layer_id':'layer1','layer_name':'Paraderos','total_features':count}
                  for name,count in [('Zona A',3),('Zona B',7)]]
        result=build_zone_comparison(analyses + [analyses[0]])
        self.assertEqual([row['value'] for row in result['data']],[3,7])
        self.assertIsNone(build_zone_comparison(analyses[:1]))
        self.assertIsNone(build_zone_comparison([dict(analysis,scope='entire_layer') for analysis in analyses]))

    def test_incomplete_tool_round_is_not_sent_to_next_model(self):
        history = [{'role':'tool', 'tool_call_id':'orphan', 'content':'ignore'},
                   {'role':'assistant', 'content':'Voy a consultar', 'metadata':{'tool_calls':[{'id':'a'}, {'id':'b'}]}},
                   {'role':'tool', 'tool_call_id':'a', 'content':'ok'},
                   {'role':'user', 'content':'Continúa'}]
        cleaned = coherent_history(history)
        self.assertEqual([message['role'] for message in cleaned], ['assistant', 'user'])
        self.assertFalse(cleaned[0]['tool_calls'])
        self.assertNotIn('tool_calls', cleaned[0]['metadata'])

    def test_complete_native_round_stays_together_under_budget(self):
        history = [{'role':'user', 'content':'x'*2000},
                   {'role':'assistant', 'metadata':{'tool_calls':[{'id':'a'}]}},
                   {'role':'tool', 'tool_call_id':'a', 'content':'ok'}]
        self.assertEqual([m['role'] for m in coherent_history(history, 500)], ['assistant','tool'])

    def test_large_results_remain_valid_json_and_do_not_claim_success(self):
        result = json.loads(bounded_tool_result({'success':True, 'data':'x'*25000}))
        self.assertFalse(result['success'])
        self.assertEqual(result['code'], 'RESULT_TOO_LARGE')


if __name__ == '__main__': unittest.main()
