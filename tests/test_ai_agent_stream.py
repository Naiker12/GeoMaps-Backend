import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from backend_test_environment import configure_test_environment

configure_test_environment()

from app.services.ia.agent_service import AgentService
from app.schemas.ia import ChatRequest, IAModelConfig


class AgentStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_unavailable_explicit_model_never_uses_another_provider(self):
        self.agent._get_model_config=AsyncMock(return_value=None)
        self.agent._get_any_active_model=AsyncMock()
        events=[json.loads(frame[6:]) async for frame in self.agent.chat_stream(ChatRequest(message='Consulta',model='missing'),self.user)]
        self.assertEqual(events[-1]['type'],'error')
        self.agent._get_any_active_model.assert_not_awaited()
        self.agent._get_or_create_conversation.assert_not_awaited()

    def setUp(self):
        self.agent = AgentService(MagicMock(commit=AsyncMock(),rollback=AsyncMock()))
        self.model = IAModelConfig(name='Fixture', provider='openai', model_id='fixture', has_function_calling=True)
        self.agent._get_model_config = AsyncMock(return_value=self.model)
        self.agent._get_or_create_conversation = AsyncMock(return_value=uuid4())
        self.agent._get_available_layers = AsyncMock(return_value=[])
        self.agent._save_audit_log = AsyncMock()
        self.agent.history_service = SimpleNamespace(get_trimmed_history=AsyncMock(return_value=[]), get_conversation_summary=AsyncMock(return_value=None),save_message=AsyncMock())
        self.agent.tools_service.get_tools_metadata = AsyncMock(return_value=[{'type':'function','function':{'name':'listar_capas_disponibles'}}])
        self.agent._execute_tool = AsyncMock(return_value={'success':True,'layers':[{'id':'layer1','name':'RUTAS'}]})
        self.user = SimpleNamespace(id=uuid4(),full_name='Fixture',email='fixture@example.com')

    async def test_two_native_rounds_stream_activity_and_final_canonical_reply(self):
        rounds = []
        async def stream(messages, tools=None):
            rounds.append(messages)
            if len(rounds) == 1:
                yield {'type':'text','content':'Consultando…'}
                yield {'type':'tool_call','tool_calls':[{'id':'call1','type':'function','function':{'name':'listar_capas_disponibles','arguments':'{}'}}]}
                yield {'type':'done','tokens_input':10,'tokens_output':2}
            else:
                yield {'type':'text','content':'RUTAS está disponible.'}
                yield {'type':'done','tokens_input':15,'tokens_output':5}
        client = SimpleNamespace(chat_stream=stream)
        with patch('app.services.ia.agent_service.LLMProviderFactory.create',return_value=client):
            events = [json.loads(frame[6:]) async for frame in self.agent.chat_stream(ChatRequest(message='Lista las capas',request_id='test-request'),self.user)]
        self.assertEqual([e['type'] for e in events], ['start','text','tool_status','tool_result','text','done'])
        self.assertEqual(events[2]['tool_call_id'], events[3]['tool_call_id'])
        self.assertEqual(events[-1]['message'], 'RUTAS está disponible.')
        self.assertEqual(events[-1]['tokens_input'],25)
        self.assertTrue(any(m.role == 'tool' and m.tool_call_id == 'call1' for m in rounds[1]))
        self.assertEqual(events[0]['request_id'],'test-request')

    async def test_model_without_enabled_tools_cannot_dispatch_native_call(self):
        self.model.has_function_calling = False
        async def stream(messages, tools=None):
            yield {'type':'tool_call','tool_calls':[{'id':'call1','function':{'name':'listar_capas_disponibles','arguments':'{}'}}]}
        with patch('app.services.ia.agent_service.LLMProviderFactory.create',return_value=SimpleNamespace(chat_stream=stream)):
            events = [json.loads(frame[6:]) async for frame in self.agent.chat_stream(ChatRequest(message='Consulta'),self.user)]
        self.assertEqual(events[-1]['type'],'error')
        self.agent._execute_tool.assert_not_awaited()

    async def test_partial_provider_error_never_emits_done(self):
        async def stream(messages, tools=None):
            yield {'type':'text','content':'Parcial'}
            yield {'type':'error','content':'Proveedor interrumpido'}
        with patch('app.services.ia.agent_service.LLMProviderFactory.create',return_value=SimpleNamespace(chat_stream=stream)):
            events = [json.loads(frame[6:]) async for frame in self.agent.chat_stream(ChatRequest(message='Consulta'),self.user)]
        self.assertEqual([e['type'] for e in events],['start','text','error'])
        self.agent._save_audit_log.assert_awaited_once()
        self.assertEqual(self.agent._save_audit_log.call_args.kwargs['status'],'error')
        self.assertEqual(self.agent.history_service.save_message.call_args.args[2],'Parcial')

    async def test_cancellation_records_partial_reply_only_once(self):
        self.agent._stream_run={'conversation_id':uuid4(),'user_id':self.user.id,'model':'Fixture','start_time':0,
            'request_id':'cancel-test','partial':'Datos parciales','tokens_input':0,'tokens_output':0}
        await self.agent.record_stream_failure('cancelled')
        await self.agent.record_stream_failure('cancelled')
        self.agent._save_audit_log.assert_awaited_once()
        self.assertEqual(self.agent._save_audit_log.call_args.kwargs['status'],'cancelled')
        self.assertEqual(self.agent.history_service.save_message.call_args.kwargs['metadata']['generation_status'],'cancelled')


if __name__ == '__main__': unittest.main()
