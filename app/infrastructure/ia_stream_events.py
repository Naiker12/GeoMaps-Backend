"""Assemble native provider stream fragments without executing textual markup."""
import json
from app.infrastructure.ia_tool_protocol import invalid_textual_tool_response

class ProviderStreamAssembler:
    def __init__(self, protocol='openai'):
        self.protocol = protocol
        self.text = ''
        self.emitted = 0
        self.calls = {}
        self.tokens_input = self.tokens_output = 0
        self.ended = False

    def feed(self, payload):
        events = []
        if payload.get('error') or payload.get('type') == 'error':
            raise ValueError('El proveedor interrumpió la respuesta')
        usage = payload.get('usage') or {}
        self.tokens_input = usage.get('prompt_tokens', self.tokens_input)
        self.tokens_output = usage.get('completion_tokens', self.tokens_output)
        if self.protocol == 'anthropic':
            kind = payload.get('type')
            index = payload.get('index', 0)
            if kind == 'message_start':
                usage = payload.get('message', {}).get('usage', {})
                self.tokens_input = usage.get('input_tokens', 0)
            if kind == 'message_delta':
                self.tokens_output = usage.get('output_tokens', self.tokens_output)
                reason = (payload.get('delta') or {}).get('stop_reason')
                if reason and reason not in ('end_turn','tool_use','stop_sequence'):
                    raise ValueError('La respuesta no terminó normalmente')
            if kind == 'message_stop': self.ended = True
            if kind == 'content_block_start':
                block = payload.get('content_block', {})
                if block.get('type') == 'tool_use':
                    self.calls[index] = {'id': block.get('id'), 'type': 'function', 'function': {'name': block.get('name'), 'arguments': ''}}
            delta = payload.get('delta', {})
            self.text += delta.get('text', '')
            if delta.get('type') == 'input_json_delta':
                self.calls[index]['function']['arguments'] += delta.get('partial_json', '')
        else:
            for choice in payload.get('choices', []):
                if choice.get('index', 0) != 0: continue
                if choice.get('finish_reason'):
                    if choice['finish_reason'] not in ('stop','tool_calls'):
                        raise ValueError('La respuesta no terminó normalmente')
                    self.ended = True
                delta = choice.get('delta') or {}
                self.text += delta.get('content') or ''
                for fragment in delta.get('tool_calls') or []:
                    index = fragment.get('index', 0)
                    call = self.calls.setdefault(index, {'id': '', 'type': 'function', 'function': {'name': '', 'arguments': ''}})
                    if fragment.get('id'): call['id'] = fragment['id']
                    signature = ((fragment.get('extra_content') or {}).get('google') or {}).get('thought_signature')
                    if signature is not None:
                        if not isinstance(signature, str) or len(signature) > 64000: raise ValueError('Metadatos del proveedor inválidos')
                        call['extra_content'] = {'google': {'thought_signature': signature}}
                    function = fragment.get('function') or {}
                    call['function']['name'] += function.get('name') or ''
                    call['function']['arguments'] += function.get('arguments') or ''
        if len(self.text) > 1_000_000 or len(self.calls) > 16 or any(len(call['function']['arguments']) > 64000 for call in self.calls.values()):
            raise ValueError('La respuesta supera los límites de tamaño')
        if invalid_textual_tool_response(self.text, []):
            raise ValueError('El modelo devolvió herramientas en un formato no válido')
        # Hold a short suffix so split protocol markers never flash in the UI.
        safe_end = max(0, len(self.text) - 32)
        if safe_end > self.emitted:
            events.append({'type': 'text', 'content': self.text[self.emitted:safe_end]})
            self.emitted = safe_end
        return events

    def finish(self):
        if not self.ended: raise ValueError('El proveedor cerró la respuesta antes de completarla')
        events = []
        if self.emitted < len(self.text): events.append({'type':'text', 'content': self.text[self.emitted:]})
        calls = list(self.calls.values())
        for call in calls:
            if not call['id'] or not call['function']['name']: raise ValueError('Llamada de herramienta incompleta')
            call['function']['arguments'] = call['function']['arguments'] or '{}'
            if not isinstance(json.loads(call['function']['arguments']), dict): raise ValueError('Argumentos de herramienta inválidos')
        if calls: events.append({'type': 'tool_call', 'tool_calls': calls})
        events.append({'type':'done', 'tokens_input':self.tokens_input, 'tokens_output':self.tokens_output})
        return events
