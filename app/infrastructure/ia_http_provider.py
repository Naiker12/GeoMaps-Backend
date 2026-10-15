import json
import httpx
from app.infrastructure.ia_llm_client import LLMProvider
from app.schemas.ia import Message
from app.infrastructure.ia_tool_protocol import invalid_textual_tool_response, tool_protocol_error

class HTTPChatProvider(LLMProvider):
    """OpenAI-compatible and Anthropic APIs, adapted to the agent contract."""
    def __init__(self, api_key, model_id, base_url, protocol='openai'):
        super().__init__(api_key, model_id)
        self.base_url = base_url
        self.protocol = protocol

    def _request_payload(self, messages, tools=None):
        headers = {'Content-Type': 'application/json'}
        if self.protocol == 'anthropic':
            headers.update({'x-api-key': self.api_key, 'anthropic-version': '2023-06-01'})
            converted, system = [], []
            for message in messages:
                if message.role == 'system':
                    system.append(message.content or '')
                    continue
                content = []
                if message.role == 'tool':
                    content = [{'type':'tool_result', 'tool_use_id':message.tool_call_id, 'content':message.content or ''}]
                    role = 'user'
                else:
                    role = 'assistant' if message.role == 'assistant' else 'user'
                    if message.content:
                        content.append({'type':'text', 'text':message.content})
                    for call in message.tool_calls or (message.metadata or {}).get('tool_calls') or []:
                        content.append({'type':'tool_use','id':call['id'],'name':call['function']['name'],'input':json.loads(call['function']['arguments'])})
                converted.append({'role':role,'content':content})
            payload = {'model':self.model_id, 'max_tokens':self.max_output_tokens, 'system':'\n'.join(system), 'messages':converted}
            if tools:
                payload['tools'] = [{'name':t['function']['name'],'description':t['function'].get('description',''),'input_schema':t['function']['parameters']} for t in tools]
            endpoint = '/messages'
        else:
            if self.api_key:
                headers['Authorization'] = 'Bearer ' + self.api_key
            converted = []
            for message in messages:
                entry = {'role':message.role,'content':message.content or ''}
                calls = message.tool_calls or (message.metadata or {}).get('tool_calls')
                if calls:
                    entry['tool_calls'] = [{key:value for key,value in call.items() if key in ('id','type','function') or (key == 'extra_content' and 'openrouter.ai' in self.base_url)} for call in calls]
                if message.tool_call_id: entry['tool_call_id'] = message.tool_call_id
                converted.append(entry)
            payload = {'model':self.model_id,'messages':converted}
            payload['max_tokens'] = self.max_output_tokens
            if tools:
                payload['tools'] = tools
                if 'openrouter.ai' in self.base_url:
                    payload['provider'] = {'require_parameters': True}
            endpoint = '/chat/completions'
        return headers, payload, endpoint

    async def chat_complete(self, messages, tools=None):
        headers, payload, endpoint = self._request_payload(messages, tools)
        try:
            async with httpx.AsyncClient(timeout=90, follow_redirects=False, trust_env=False) as client:
                response = await client.post(self.base_url + endpoint, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
            if self.protocol == 'anthropic':
                if data.get('stop_reason') and data['stop_reason'] not in ('end_turn','tool_use','stop_sequence'):
                    raise ValueError('Respuesta incompleta')
                content = ''.join(b['text'] for b in data.get('content',[]) if b['type']=='text')
                calls = [{'id':b['id'],'type':'function','function':{'name':b['name'],'arguments':json.dumps(b['input'])}} for b in data.get('content',[]) if b['type']=='tool_use']
                usage = data.get('usage',{})
                token_in, token_out = usage.get('input_tokens',0), usage.get('output_tokens',0)
            else:
                if data['choices'][0].get('finish_reason') and data['choices'][0]['finish_reason'] not in ('stop','tool_calls'):
                    raise ValueError('Respuesta incompleta')
                message = data['choices'][0]['message']
                content, calls = message.get('content') or '', message.get('tool_calls') or []
                usage = data.get('usage',{})
                token_in, token_out = usage.get('prompt_tokens',0), usage.get('completion_tokens',0)
            if invalid_textual_tool_response(content, calls):
                return tool_protocol_error()
            return {'status':'success','message':{'role':'assistant','content':content,'tool_calls':calls or None},'tokens_input':token_in,'tokens_output':token_out}
        except (httpx.HTTPError, ValueError, KeyError, IndexError):
            return {'status':'error','error_message':'No se pudo completar la solicitud con el proveedor.','status_code':502,'error_code':'PROVIDER_ERROR'}

    async def chat_stream(self, messages, tools=None):
        from app.infrastructure.ia_stream_events import ProviderStreamAssembler
        headers, payload, endpoint = self._request_payload(messages, tools)
        payload['stream'] = True
        if self.protocol != 'anthropic':
            payload['stream_options'] = {'include_usage': True}
        assembler = ProviderStreamAssembler(self.protocol)
        try:
            async with httpx.AsyncClient(timeout=90, follow_redirects=False, trust_env=False) as client:
                async with client.stream('POST', self.base_url + endpoint, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith('data:'): continue
                        data = line[5:].strip()
                        if not data or data == '[DONE]': continue
                        for event in assembler.feed(json.loads(data)):
                            yield event
            for event in assembler.finish():
                yield event
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            yield {'type':'error', 'content':'El proveedor interrumpió la respuesta o devolvió un formato inválido. Reintenta o selecciona otro modelo.'}
