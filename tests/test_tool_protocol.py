import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from app.infrastructure.ia_tool_protocol import invalid_textual_tool_response
from app.infrastructure.ia_http_provider import HTTPChatProvider

class ToolProtocolTests(unittest.TestCase):
    def test_textual_calls_are_errors(self):
        for text in ('<|tool_call_start|>activate_layer()<|tool_call_end|>', '<tool_call><function=consultar_datos_tabla>RUTAS</function></tool_call>'):
            self.assertTrue(invalid_textual_tool_response(text, []))

    def test_native_calls_and_plain_text_are_preserved(self):
        self.assertFalse(invalid_textual_tool_response('Consultando datos', [{'id': 'native'}]))
        self.assertFalse(invalid_textual_tool_response('Puedes activar la capa RUTAS.', []))
        self.assertFalse(invalid_textual_tool_response('', []))

class HTTPToolProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def call_provider(self, content, calls):
        response = MagicMock()
        response.json.return_value = {'choices': [{'message': {'content': content, 'tool_calls': calls}}]}
        client = AsyncMock()
        client.post.return_value = response
        context = AsyncMock()
        context.__aenter__.return_value = client
        with patch('app.infrastructure.ia_http_provider.httpx.AsyncClient', return_value=context):
            provider = HTTPChatProvider('fixture-key', 'fixture-model', 'https://example.invalid')
            return await provider.chat_complete([])

    async def test_leaked_text_is_not_returned_as_success(self):
        result = await self.call_provider('<tool_call><function=activate_layer>RUTAS</function></tool_call>', [])
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error_code'], 'INVALID_TOOL_FORMAT')

    async def test_native_tool_call_survives_adapter(self):
        calls = [{'id': 'native', 'type': 'function', 'function': {'name': 'activate_layer', 'arguments': '{}'}}]
        result = await self.call_provider('', calls)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['message']['tool_calls'], calls)

if __name__ == '__main__':
    unittest.main()
