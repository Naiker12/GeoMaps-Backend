"""Keep native tool histories coherent and bound model input/output work."""
import json


def coherent_history(messages, max_chars=40000):
    groups = []
    for message in messages:
        metadata = message.get('metadata') or {}
        calls = message.get('tool_calls') or metadata.get('tool_calls') or []
        if message.get('role') == 'tool':
            if groups and any(call.get('id') == message.get('tool_call_id') for call in groups[-1][0].get('tool_calls', [])):
                groups[-1].append(message)
            continue
        entry = dict(message)
        if calls:
            entry['tool_calls'] = calls
        groups.append([entry])
    valid = []
    for group in groups:
        calls = group[0].get('tool_calls', [])
        answered = {m.get('tool_call_id') for m in group[1:]}
        if calls and any(call.get('id') not in answered for call in calls):
            group = [dict(group[0], tool_calls=None, metadata={k:v for k,v in (group[0].get('metadata') or {}).items() if k != 'tool_calls'})]
            if not group[0].get('content'):
                continue
        valid.append(group)
    selected, length = [], 0
    for group in reversed(valid):
        size = len(json.dumps(group, ensure_ascii=False, default=str))
        if length + size > max_chars:
            break
        selected[:0] = group
        length += size
    return selected


def bounded_tool_result(result, max_chars=20000):
    encoded = json.dumps(result, ensure_ascii=False, default=str)
    if len(encoded) <= max_chars:
        return encoded
    if isinstance(result, dict) and result.get('map_actions'):
        compact = {key:value for key,value in result.items() if key != 'map_actions'}
        compact['map_actions_proposed'] = len(result['map_actions'])
        encoded = json.dumps(compact, ensure_ascii=False, default=str)
        if len(encoded) <= max_chars:
            return encoded
    # Do not truncate JSON mid-field or turn incomplete evidence into a success.
    return json.dumps({'success': False, 'code': 'RESULT_TOO_LARGE',
                       'error': 'El resultado supera el presupuesto. Consulta menos campos o un filtro más específico.'})


def validate_native_calls(calls, tools):
    allowed = {tool['function']['name'] for tool in tools}
    if not isinstance(calls, list) or len(calls) > 8:
        raise ValueError('Demasiadas llamadas de herramientas')
    identifiers = set()
    for call in calls:
        identifier = call.get('id')
        function = call.get('function') or {}
        arguments = function.get('arguments', '')
        if not identifier or identifier in identifiers or function.get('name') not in allowed:
            raise ValueError('El modelo solicitó una herramienta no habilitada o una llamada duplicada')
        if not isinstance(arguments, str) or len(arguments) > 100000 or not isinstance(json.loads(arguments), dict):
            raise ValueError('La llamada de herramienta tiene argumentos inválidos')
        identifiers.add(identifier)
