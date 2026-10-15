"""Compact conversation facts without inventing model reasoning or training."""
import json

def build_conversation_memory(messages, max_chars=6000):
    entries = []
    for message in messages:
        metadata = message.metadata or {}
        if metadata.get('kind') == 'conversation_memory':
            continue
        if message.role == 'user':
            entries.append('Solicitud anterior: ' + (message.content or '')[:240])
            geo = metadata.get('geo_context') or {}
            if geo:
                entries.append('Contexto declarado: ' + json.dumps(geo, ensure_ascii=False, default=str)[:700])
        elif message.role == 'tool':
            try:
                result = json.loads(message.content or '{}')
            except (TypeError, ValueError):
                continue
            if isinstance(result, dict):
                facts = {key: result[key] for key in ('success', 'layer', 'layer_name', 'count', 'total', 'analysis', 'error') if key in result}
                entries.append('Resultado de ' + str(metadata.get('function', 'herramienta')) + ': ' + json.dumps(facts, ensure_ascii=False, default=str)[:1000])
    # Retain recent evidence, not a generated account of private reasoning.
    text = '\n'.join(entries)
    return text[-max_chars:]
