import importlib.util
import unittest
from pathlib import Path
from uuid import UUID
from unittest.mock import AsyncMock, Mock, patch
from fastapi import HTTPException
from backend_test_environment import configure_test_environment
configure_test_environment()
spec = importlib.util.spec_from_file_location('tested_ia_router', Path(__file__).parents[1] / 'app/api/v1/admin/ia_monitoring.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ID = UUID('11111111-1111-4111-8111-111111111111')

def result(row=None):
    value = Mock()
    value.mappings.return_value.first.return_value = row
    return value

class DefaultTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_update_is_locked_and_clears_old_default_before_setting_new(self):
        db=AsyncMock()
        db.execute.side_effect=[result(),result({'is_active':True}),result(),result()]
        await module.set_default_model(ID,db)
        queries=[str(call.args[0]) for call in db.execute.call_args_list]
        self.assertIn('pg_advisory_xact_lock',queries[0])
        self.assertIn('is_default = false',queries[2])
        self.assertIn('is_default = true',queries[3])
        db.commit.assert_awaited_once()
    async def test_inactive_model_cannot_be_default(self):
        db=AsyncMock();db.execute.side_effect=[result(),result({'is_active':False})]
        with self.assertRaises(HTTPException) as error: await module.set_default_model(ID,db)
        self.assertEqual(error.exception.status_code,409)
        db.commit.assert_not_awaited()
    async def test_default_cannot_be_disabled_or_deleted(self):
        db=AsyncMock();db.execute.return_value=result({'is_default':True})
        with self.assertRaises(HTTPException): await module.update_model_config(ID,{'is_active':False},db)
        with self.assertRaises(HTTPException): await module.delete_model_config(ID,db)
        db.commit.assert_not_awaited()
    async def test_patch_rejects_arbitrary_sql_identifiers(self):
        db=AsyncMock()
        with self.assertRaises(HTTPException): await module.update_model_config(ID,{'api_key_encrypted':'fake'},db)
        db.execute.assert_not_awaited()
    async def test_selected_model_must_come_from_discovery(self):
        connection=module.ConnectModelRequest(provider='ollama',base_url='http://localhost:11434/v1',model_id='not-in-catalog',name='Fake')
        db=AsyncMock()
        with patch.object(module,'discover_models',AsyncMock(return_value=[{'id':'different','name':'Different'}])):
            with self.assertRaises(HTTPException): await module.connect_provider_model(connection,db)
        db.execute.assert_not_awaited()

if __name__=='__main__': unittest.main()
