import unittest
from unittest.mock import patch
from cryptography.fernet import Fernet
from fastapi import HTTPException
import httpx
from backend_test_environment import configure_test_environment
configure_test_environment()
from app.services.ia import provider_connections as module
from app.schemas.ia import IAModelConfig, ChatRequest
from app.infrastructure.ia_llm_client import LLMProviderFactory
from app.infrastructure.ia_http_provider import HTTPChatProvider

class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    def test_secret_is_encrypted_and_never_serialized(self):
        with patch.object(module.settings, 'AI_PROVIDER_ENCRYPTION_KEY', Fernet.generate_key().decode()):
            encrypted = module.encrypt_key('fake-unit-test-key')
            self.assertNotIn('fake-unit-test-key', encrypted)
            self.assertEqual(module.decrypt_key(encrypted), 'fake-unit-test-key')
            config = IAModelConfig(name='Test', provider='openai', model_id='test', api_key_encrypted=encrypted)
            self.assertNotIn('api_key_encrypted', config.model_dump())
    def test_encryption_key_required(self):
        with patch.object(module.settings, 'AI_PROVIDER_ENCRYPTION_KEY', None):
            with self.assertRaises(HTTPException): module.encrypt_key('fake')
    def test_metadata_and_credential_urls_rejected(self):
        for url in ['http://169.254.169.254/v1', 'http://user:pass@localhost/v1', 'https://api.openai.com/v1?key=fake']:
            with self.assertRaises(HTTPException): module.validate_url('custom', url)
    def test_cloud_endpoint_cannot_be_replaced(self):
        with self.assertRaises(HTTPException): module.validate_url('openai', 'https://example.com/v1')
    def test_omitted_model_uses_server_default(self):
        self.assertIsNone(ChatRequest(message='hello').model)
    def test_factory_does_not_force_google(self):
        with patch('app.services.ia.provider_connections.validate_url', return_value='https://api.openai.com/v1'):
            self.assertIsInstance(LLMProviderFactory.create('openai','fake','test'),HTTPChatProvider)

    async def test_discovery_paginates_and_filters_gemini_models(self):
        requests=[]
        def handle(request):
            requests.append(request)
            if len(requests)==1:
                return httpx.Response(200,json={'models':[{'name':'models/chat-a','supportedGenerationMethods':['generateContent']},{'name':'models/embed','supportedGenerationMethods':['embedContent']}],'nextPageToken':'next'})
            return httpx.Response(200,json={'models':[{'name':'models/chat-b','displayName':'Chat B','supportedGenerationMethods':['generateContent']}]})
        original=httpx.AsyncClient
        with patch.object(module,'validate_url',return_value='https://generativelanguage.googleapis.com/v1beta'), patch.object(module.httpx,'AsyncClient',side_effect=lambda **kw: original(transport=httpx.MockTransport(handle),**kw)):
            result=await module.discover_models(module.ConnectionRequest(provider='google',base_url='https://generativelanguage.googleapis.com/v1beta',api_key='fake'))
        self.assertEqual([m['id'] for m in result],['chat-b','chat-a'])
        self.assertEqual(requests[1].url.params['pageToken'],'next')
        self.assertEqual(requests[0].headers['x-goog-api-key'],'fake')
    async def test_rejected_key_does_not_leak_provider_response(self):
        original=httpx.AsyncClient
        with patch.object(module,'validate_url',return_value='https://api.openai.com/v1'), patch.object(module.httpx,'AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(lambda r:httpx.Response(401,json={'secret':'fake-sensitive-echo'})),**kw)):
            with self.assertRaises(HTTPException) as error:
                await module.discover_models(module.ConnectionRequest(provider='openai',base_url='https://api.openai.com/v1',api_key='fake'))
        self.assertNotIn('fake-sensitive-echo',str(error.exception))
    async def test_openai_completion_usage_and_model(self):
        original=httpx.AsyncClient
        def handle(request):
            import json
            self.assertEqual(json.loads(request.content)['model'],'test-model')
            return httpx.Response(200,json={'choices':[{'message':{'content':'Hello'}}],'usage':{'prompt_tokens':3,'completion_tokens':2}})
        with patch('app.infrastructure.ia_http_provider.httpx.AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(handle),**kw)):
            from app.schemas.ia import Message
            result=await HTTPChatProvider('fake','test-model','https://api.openai.com/v1').chat_complete([Message(role='user',content='Hi')])
        self.assertEqual(result['tokens_input'],3)
        self.assertEqual(result['message']['content'],'Hello')

if __name__ == '__main__': unittest.main()
