import ast,unittest
from pathlib import Path
source=ast.parse(Path('alembic/env.py').read_text(encoding='utf-8'))
function=next(node for node in source.body if isinstance(node,ast.FunctionDef) and node.name=='include_object')
namespace={}
exec(compile(ast.Module(body=[function],type_ignores=[]),'alembic/env.py','exec'),namespace)
include=namespace['include_object']
class MigrationFilterTests(unittest.TestCase):
 def test_unmapped_remote_table_is_not_deleted(self):
  self.assertFalse(include(None,'ia_models_config','table',True,None))
 def test_postgis_table_is_protected(self):
  self.assertFalse(include(None,'spatial_ref_sys','table',True,None))
 def test_managed_tables_can_be_compared(self):
  self.assertTrue(include(None,'users','table',True,object()))
 def test_new_orm_tables_can_be_created(self):
  self.assertTrue(include(None,'new_table','table',False,None))
if __name__=='__main__':unittest.main()
