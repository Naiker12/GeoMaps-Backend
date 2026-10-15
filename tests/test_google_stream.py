import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from app.infrastructure.ia_llm_client import GeminiProvider
from app.schemas.ia import Message


def part(text=None, thought=False, function=None):
    return NS(text=text, thought=thought, function_call=function)


def chunk(parts, finish=None, tokens=0):
    return NS(candidates=[NS(content=NS(parts=parts),finish_reason=finish)],
              usage_metadata=NS(prompt_token_count=10,candidates_token_count=tokens))


class GoogleStreamTests(unittest.IsolatedAsyncioTestCase):
    def test_other_model_native_history_becomes_reference_text(self):
        provider=object.__new__(GeminiProvider);provider.model_id='gemini-fixture'
        contents,_=provider._convert_messages([
            Message(role='assistant',metadata={'model':'other-model'},tool_calls=[{'id':'a','function':{'name':'catalog','arguments':'{}'}}]),
            Message(role='tool',tool_call_id='a',metadata={'function':'catalog'},content='{"count":2}')])
        self.assertFalse(any(part.function_call or part.function_response for content in contents for part in content.parts))
        self.assertIn('count',contents[-1].parts[0].text)

    def test_opaque_signature_is_restored_without_exposing_reasoning(self):
        provider=object.__new__(GeminiProvider)
        contents,_=provider._convert_messages([Message(role='assistant',tool_calls=[{'id':'a','function':{'name':'catalog','arguments':'{}'},'extra_content':{'google':{'thought_signature':'c2ln'}}}])])
        self.assertEqual(contents[0].parts[0].thought_signature,b'sig')

    def test_native_call_from_message_field_is_preserved_on_model_switch(self):
        provider = object.__new__(GeminiProvider)
        contents, _ = provider._convert_messages([Message(role='assistant', tool_calls=[{'id':'a','function':{'name':'catalog','arguments':'{}'}}])])
        self.assertEqual(contents[0].parts[0].function_call.name,'catalog')

    async def run_stream(self, chunks):
        async def sdk_stream():
            for value in chunks: yield value
        provider = object.__new__(GeminiProvider)
        provider.model_id = 'fixture'; provider.max_output_tokens = 1024
        call = AsyncMock(return_value=sdk_stream())
        provider.client = NS(aio=NS(models=NS(generate_content_stream=call)))
        events = [event async for event in provider.chat_stream([Message(role='user',content='Consulta')])]
        call.assert_awaited_once()
        self.assertEqual(call.call_args.kwargs['config'].max_output_tokens,1024)
        return events

    async def test_real_sdk_await_contract_and_private_thoughts_are_excluded(self):
        events = await self.run_stream([chunk([part('privado',thought=True),part('Resultado público')], 'STOP',5)])
        self.assertEqual(''.join(e['content'] for e in events if e['type']=='text'),'Resultado público')
        self.assertNotIn('privado',str(events))
        self.assertEqual(events[-1]['tokens_output'],5)

    async def test_same_tool_multiple_native_calls_have_unique_ids(self):
        function = NS(name='catalog',args={})
        events = await self.run_stream([chunk([part(function=function),part(function=function)], 'STOP')])
        calls = next(event for event in events if event['type']=='tool_call')['tool_calls']
        self.assertEqual(len({call['id'] for call in calls}),2)

    async def test_split_textual_protocol_is_rejected_before_display(self):
        events = await self.run_stream([chunk([part('<tool_')]),chunk([part('call><function=activate_layer>')],'STOP')])
        self.assertEqual(events[-1]['type'],'error')
        self.assertFalse(any(event['type']=='text' for event in events))

    async def test_incomplete_finish_is_not_successful(self):
        events = await self.run_stream([chunk([part('Parcial')],'MAX_TOKENS')])
        self.assertEqual(events[-1]['type'],'error')
        self.assertFalse(any(event['type']=='done' for event in events))


if __name__ == '__main__': unittest.main()
