def build_zone_comparison(analyses):
    results = {}
    for analysis in analyses:
        if analysis.get('zone_name') and analysis.get('scope') == 'zone_polygon' and analysis.get('count_is_complete'):
            key = (analysis['zone_name'], analysis.get('layer_id'))
            results[key] = analysis
    if len({zone for zone, _ in results}) < 2:
        return None
    return {'type':'table', 'title':'Resultados por zona consultada',
            'label':'Zona y capa', 'interactive_filter':False,
            'subtitle':'Conteo de geometrías válidas que intersectan cada zona; una geometría puede pertenecer a más de una zona.',
            'data':[{'name':analysis['zone_name'] + ' · ' + analysis.get('layer_name','Capa consultada'),'layer':analysis.get('layer_name','Capa consultada'), 'value':analysis['total_features']} for analysis in results.values()],
            'columns':[{'key':'name','label':'Zona y capa'},{'key':'layer','label':'Capa'},{'key':'value','label':'Elementos'}],
            'report_available':True}
