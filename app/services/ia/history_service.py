import json
import redis.asyncio as aioredis
from uuid import UUID
from typing import List, Optional, Any, Dict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.ia import Conversation, MessageRead
from app.core.config import settings

CACHE_TTL = 3600   # 1 hora

class HistoryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._redis: Optional[aioredis.Redis] = None

    async def _get_redis(self) -> aioredis.Redis:
        if not self._redis:
            self._redis = aioredis.from_url(
                getattr(settings, 'REDIS_URL', 'redis://localhost:6379'),
                encoding='utf-8',
                decode_responses=True
            )
        return self._redis


    # Cache key helpers
    def _cache_key_history(self, conv_id: UUID) -> str:
        return f"geomaps:history:{conv_id}"

    def _cache_key_summary(self, conv_id: UUID) -> str:
        return f"geomaps:summary:{conv_id}"

    # Obtener historial (con cache)
    async def get_messages(self, conversation_id: Optional[UUID], user_id: UUID) -> List[MessageRead]:
        if not conversation_id:
            return []

        try:
            r = await self._get_redis()
            cached = await r.get(self._cache_key_history(conversation_id))
            if cached:
                raw = json.loads(cached)
                return [MessageRead(**m) for m in raw]
        except Exception:
            pass  # Redis falló → seguir con DB

        # Verificar propiedad
        check = await self.db.execute(
            text("SELECT id FROM ia_conversations WHERE id = :cid AND user_id = :uid"),
            {"cid": conversation_id, "uid": user_id}
        )
        if not check.fetchone():
            return []

        stmt = text("""
            SELECT id, role, content, tool_call_id, metadata, created_at
            FROM ia_messages
            WHERE conversation_id = :cid
            ORDER BY created_at ASC
        """)
        result = await self.db.execute(stmt, {"cid": conversation_id})
        messages = [MessageRead(**row) for row in result.mappings().all()]

        # Guardar en cache
        try:
            r = await self._get_redis()
            await r.set(
                self._cache_key_history(conversation_id),
                json.dumps([m.dict() for m in messages], default=str),
                ex=CACHE_TTL
            )
        except Exception:
            pass

        return messages

    # Historial recortado con resumen de memoria
    async def get_trimmed_history(
        self,
        conversation_id: Optional[UUID],
        user_id: UUID,
        max_messages: int = 10
    ) -> List[MessageRead]:
        messages = await self.get_messages(conversation_id, user_id)
        if len(messages) <= max_messages:
            return messages
        return messages[-max_messages:]

    # Resumen de memoria de largo plazo
    async def get_conversation_summary(self, conversation_id: UUID) -> Optional[str]:
        """
        Retorna un resumen en texto de las capas analizadas y datos vistos.
        """
        try:
            r = await self._get_redis()
            summary = await r.get(self._cache_key_summary(conversation_id))
            if summary:
                return summary
        except Exception:
            pass
        return None

    async def save_conversation_summary(self, conversation_id: UUID, summary: str):
        """Guarda el resumen generado por el agente para memoria de largo plazo."""
        try:
            r = await self._get_redis()
            await r.set(
                self._cache_key_summary(conversation_id),
                summary,
                ex=86400  # 24 horas
            )
        except Exception:
            pass

    # Guardar mensaje (invalida cache)
    async def save_message(
        self,
        conversation_id: Optional[UUID],
        role: str,
        content: Optional[str] = None,
        metadata: dict = None,
        tool_call_id: str = None
    ):
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

        # Invalidar cache de historial
        try:
            r = await self._get_redis()
            await r.delete(self._cache_key_history(conversation_id))
        except Exception:
            pass

    # ── Resto de métodos sin cambios ───────────
    async def list_conversations(self, user_id: UUID) -> List[Conversation]:
        stmt = text("""
            SELECT id, title, model_id, created_at, updated_at
            FROM ia_conversations
            WHERE user_id = (:uid)::uuid
            ORDER BY updated_at DESC
        """)
        result = await self.db.execute(stmt, {"uid": str(user_id)})
        return [Conversation(**row) for row in result.mappings().all()]

    async def create_conversation(self, user_id: UUID, title: str, model_id: str) -> UUID:
        stmt = text("""
            INSERT INTO ia_conversations (user_id, title, model_id)
            VALUES (:uid, :title, :mid)
            RETURNING id
        """)
        result = await self.db.execute(stmt, {
            "uid": user_id, "title": title, "mid": model_id
        })
        return result.scalar()

    async def delete_conversation(self, conversation_id: UUID, user_id: UUID) -> bool:
        stmt = text("DELETE FROM ia_conversations WHERE id = :cid AND user_id = :uid")
        result = await self.db.execute(stmt, {"cid": conversation_id, "uid": user_id})
        try:
            r = await self._get_redis()
            await r.delete(self._cache_key_history(conversation_id))
            await r.delete(self._cache_key_summary(conversation_id))
        except Exception:
            pass
        return result.rowcount > 0
