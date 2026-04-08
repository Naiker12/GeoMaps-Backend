import json
from uuid import UUID
from typing import List, Dict, Optional, Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.ia import Conversation, MessageRead

class HistoryService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_conversations(self, user_id: UUID) -> List[Conversation]:
        """Lista las conversaciones del usuario."""
        stmt = text("SELECT id, title, model_id, created_at, updated_at FROM ia_conversations WHERE user_id = (:uid)::uuid ORDER BY updated_at DESC")
        result = await self.db.execute(stmt, {"uid": str(user_id)})
        return [Conversation(**row) for row in result.mappings().all()]

    async def get_messages(self, conversation_id: Optional[UUID], user_id: UUID) -> List[MessageRead]:
        """Obtiene historial completo de mensajes verificando propiedad por usuario."""
        if not conversation_id:
            return []

        # Verificar propiedad
        check = await self.db.execute(text("SELECT id FROM ia_conversations WHERE id = :cid AND user_id = :uid"), 
                                {"cid": conversation_id, "uid": user_id})
        if not check.fetchone():
            return []

        stmt = text("SELECT id, role, content, tool_call_id, metadata, created_at FROM ia_messages WHERE conversation_id = :cid ORDER BY created_at ASC")
        result = await self.db.execute(stmt, {"cid": conversation_id})
        return [MessageRead(**row) for row in result.mappings().all()]

    async def get_trimmed_history(self, conversation_id: Optional[UUID], user_id: UUID, max_messages: int = 8) -> List[MessageRead]:
        """Obtiene el historial limitado para optimizar tokens."""
        messages = await self.get_messages(conversation_id, user_id)
        if len(messages) <= max_messages:
            return messages
        
        # Simular un resumen para historial antiguo (por ahora se trunca simplemente, 
        # o se podría agregar un mensaje del sistema resumiendo el principio)
        recent = messages[-max_messages:]
        return recent

    async def save_message(self, conversation_id: Optional[UUID], role: str, content: Optional[str] = None, metadata: dict = None, tool_call_id: str = None):
        """Guarda un mensaje en la tabla ia_messages."""
        if not conversation_id:
            return

        stmt = text("""
            INSERT INTO ia_messages (conversation_id, role, content, metadata, tool_call_id)
            VALUES (:cid, :role, :content, :meta, :tcid)
        """)
        await self.db.execute(stmt, {
            "cid": conversation_id,
            "role": role,
            "content": content,
            "meta": json.dumps(metadata or {}),
            "tcid": tool_call_id
        })

    async def create_conversation(self, user_id: UUID, title: str, model_id: str) -> UUID:
        """Crea una nueva conversación."""
        stmt = text("""
            INSERT INTO ia_conversations (user_id, title, model_id)
            VALUES (:uid, :title, :mid)
            RETURNING id
        """)
        result = await self.db.execute(stmt, {
            "uid": user_id,
            "title": title,
            "mid": model_id
        })
        return result.scalar()

    async def delete_conversation(self, conversation_id: UUID, user_id: UUID) -> bool:
        """Elimina una conversación."""
        stmt = text("DELETE FROM ia_conversations WHERE id = :cid AND user_id = :uid")
        result = await self.db.execute(stmt, {"cid": conversation_id, "uid": user_id})
        return result.rowcount > 0
