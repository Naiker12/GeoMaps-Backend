import unittest
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock
from app.services.ia.conversation_memory import build_conversation_memory
from app.services.ia.history_service import HistoryService

class MemoryTests(unittest.IsolatedAsyncioTestCase):
    def test_memory_is_bounded_and_preserves_tool_evidence(self):
        messages = [SimpleNamespace(role='user', content='Analiza RUTAS', metadata={}), SimpleNamespace(role='tool', content='{"success":true,"count":22,"layer":"RUTAS"}', metadata={'function':'contar'})]
        memory = build_conversation_memory(messages)
        self.assertIn('22', memory)
        self.assertIn('RUTAS', memory)
        self.assertLessEqual(len(build_conversation_memory(messages * 50, 500)), 500)

    async def test_cache_never_bypasses_conversation_owner(self):
        db = MagicMock(); result = MagicMock(); result.fetchone.return_value = None
        db.execute = AsyncMock(return_value=result)
        service = HistoryService(db)
        service._get_redis = AsyncMock()
        self.assertEqual(await service.get_messages(uuid4(), uuid4()), [])
        service._get_redis.assert_not_called()

    async def test_summary_uses_messages_before_trimming(self):
        service = HistoryService(MagicMock())
        service.get_messages = AsyncMock(return_value=[SimpleNamespace(role='user', content=f'Pregunta {i}', metadata={}) for i in range(25)])
        service.get_conversation_summary = AsyncMock(return_value=None)
        service.save_conversation_summary = AsyncMock()
        history = await service.get_trimmed_history(uuid4(), uuid4(), max_messages=10)
        self.assertEqual(len(history), 10)
        service.save_conversation_summary.assert_awaited_once()
        self.assertIn('Pregunta 0', service.save_conversation_summary.call_args.args[1])

if __name__ == '__main__': unittest.main()
