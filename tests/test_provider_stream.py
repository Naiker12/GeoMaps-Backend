import unittest
from app.infrastructure.ia_stream_events import ProviderStreamAssembler

class ProviderStreamTests(unittest.TestCase):
    def test_opaque_tool_signature_survives_streaming(self):
        stream=ProviderStreamAssembler()
        stream.feed({'choices':[{'delta':{'tool_calls':[{'index':0,'id':'a','function':{'name':'catalog','arguments':'{}'},'extra_content':{'google':{'thought_signature':'c2ln'}}}]},'finish_reason':'tool_calls'}]})
        calls=next(event for event in stream.finish() if event['type']=='tool_call')['tool_calls']
        self.assertEqual(calls[0]['extra_content']['google']['thought_signature'],'c2ln')
    def test_text_arrives_before_completion_and_utf8_is_preserved(self):
        stream = ProviderStreamAssembler()
        events = stream.feed({'choices':[{'delta':{'content':'Bogotá y Cartagena: ' + 'datos '*20}}]})
        self.assertTrue(events)
        stream.feed({'choices':[{'delta':{},'finish_reason':'stop'}]})
        self.assertEqual(''.join(e['content'] for e in events + stream.finish() if e['type']=='text'), stream.text)

    def test_tool_arguments_are_assembled(self):
        stream = ProviderStreamAssembler()
        stream.feed({'choices':[{'delta':{'tool_calls':[{'index':0,'id':'call1','function':{'name':'activate_layer','arguments':'{"layer_'}}]}}]})
        stream.feed({'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'arguments':'name":"RUTAS"}'}}]},'finish_reason':'tool_calls'}]})
        calls = next(event for event in stream.finish() if event['type']=='tool_call')['tool_calls']
        self.assertEqual(calls[0]['function']['arguments'], '{"layer_name":"RUTAS"}')

    def test_interrupted_and_textual_tools_are_errors(self):
        with self.assertRaises(ValueError): ProviderStreamAssembler().finish()
        with self.assertRaises(ValueError): ProviderStreamAssembler().feed({'choices':[{'delta':{'content':'<tool_call><function=activate_layer>'}}]})

    def test_anthropic_stream(self):
        stream = ProviderStreamAssembler('anthropic')
        stream.feed({'type':'message_start','message':{'usage':{'input_tokens':12}}})
        stream.feed({'type':'content_block_delta','delta':{'type':'text_delta','text':'Resultado'}})
        stream.feed({'type':'message_stop'})
        self.assertEqual(stream.finish()[0]['content'], 'Resultado')

if __name__ == '__main__': unittest.main()
