import importlib.util
import tempfile
import unittest
from pathlib import Path
from app.services.export.typst_service import TypstPDFService

class TypstTextRegression(unittest.TestCase):
    def test_escapes_quoted_strings_and_markup_characters(self):
        with tempfile.TemporaryDirectory() as directory:
            service = TypstPDFService(directory)
            escaped = service._t('"Barrio" @reference $USD [área] #dato')
            for character in ['"', '@', '$', '[', ']', '#']:
                self.assertIn(chr(92) + character, escaped)

    @unittest.skipUnless(importlib.util.find_spec('typst'), 'Typst Python is required')
    def test_compiles_report_with_quotes_and_multiline_text(self):
        with tempfile.TemporaryDirectory() as directory:
            service = TypstPDFService(directory)
            report = {'title':'Análisis "Barú" [prueba]','ai_interpretation':'Primera línea.\nSegunda con @referencia y $USD.','kpis':[{'label':'Barrios','value':170}], 'indicator_table':[{'label':'Área','value':'4965.8 ha'}]}
            source = Path(directory) / 'test.typ'
            target = Path(directory) / 'test.pdf'
            source.write_text(service._build_typst_source(report, {}), encoding='utf-8')
            service._compile_typst(source, target)
            self.assertTrue(target.read_bytes().startswith(b'%PDF-'))

if __name__ == '__main__': unittest.main()
