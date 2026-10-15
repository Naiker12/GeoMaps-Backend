import json
import logging
import redis.asyncio as aioredis
from uuid import UUID
from typing import List, Optional, Any, Dict
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.ia import Conversation, MessageRead, IASuggestion
from app.core.config import settings
from app.services.ia.conversation_memory import build_conversation_memory

class HistoryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._redis: Optional[aioredis.Redis] = None
        self.logger = logging.getLogger(__name__)

    async def _get_redis(self) -> aioredis.Redis:
        if not self._redis:
            self._redis = aioredis.from_url(
                getattr(settings, 'REDIS_URL', 'redis://localhost:6379'),
                encoding='utf-8',
                decode_responses=True
            )
        return self._redis


    # Helpers para llaves de caché
    def _cache_key_history(self, conv_id: UUID) -> str:
        return f"geomaps:history:{conv_id}"

    def _cache_key_summary(self, conv_id: UUID) -> str:
        return f"geomaps:summary:{conv_id}"

    # Obtener historial (con cache)
    async def get_messages(self, conversation_id: Optional[UUID], user_id: UUID) -> List[MessageRead]:
        if not conversation_id:
            return []

        check = await self.db.execute(
            text("SELECT id FROM ia_conversations WHERE id = :cid AND user_id = :uid"),
            {"cid": conversation_id, "uid": user_id}
        )
        if not check.fetchone():
            return []

        try:
            r = await self._get_redis()
            cached = await r.get(self._cache_key_history(conversation_id))
            if cached:
                raw = json.loads(cached)
                return [MessageRead(**m) for m in raw]
        except Exception:
            pass  # Redis falló → seguir con DB

        stmt = text("""
            SELECT id, role, content, tool_call_id, metadata, created_at
            FROM ia_messages
            WHERE conversation_id = :cid
            ORDER BY created_at ASC
        """)
        result = await self.db.execute(stmt, {"cid": conversation_id})
        messages = []
        for row in result.mappings().all():
            try:
                d = dict(row)
                if isinstance(d.get("metadata"), str):
                    d["metadata"] = json.loads(d["metadata"])
                messages.append(MessageRead.model_validate(d))
            except Exception as e:
                self.logger.error(f"Error al procesar mensaje: {e}")


        # Guardar en cache
        try:
            r = await self._get_redis()
            await r.set(
                self._cache_key_history(conversation_id),
                json.dumps([m.model_dump() for m in messages], default=str),
                ex=settings.REDIS_TTL_HISTORY
            )
        except Exception:
            pass

        return messages

    # Historial recortado con resumen de memoria
    async def get_trimmed_history(
        self,
        conversation_id: Optional[UUID],
        user_id: UUID,
        max_messages: int = 20
    ) -> List[MessageRead]:
        messages = [message for message in await self.get_messages(conversation_id, user_id)
                    if (message.metadata or {}).get('kind') != 'conversation_memory']
        if len(messages) > max_messages and conversation_id:
            summary = build_conversation_memory(messages[:-max_messages])
            if summary:
                previous = await self.get_conversation_summary(conversation_id)
                if summary != previous:
                    await self.save_conversation_summary(conversation_id, summary)
        if len(messages) <= max_messages:
            return messages
            
        # Tomamos el recorte inicial
        trimmed = messages[-max_messages:]
        
        # Ajuste 1: Asegurar que el primer mensaje del historial sea de un usuario
        # para que la IA tenga contexto claro de quién empezó la interacción actual.
        while trimmed and trimmed[0].role != "user":
            trimmed.pop(0)
            
        # Ajuste 2: Evitar que el historial empiece con una respuesta de herramienta 
        # sin su correspondiente llamada (que estara en los mensajes eliminados).
        while trimmed and trimmed[0].role == "tool":
            trimmed.pop(0)
            
        return trimmed

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
        result = await self.db.execute(text("""
            SELECT content FROM ia_messages
            WHERE conversation_id = :cid AND metadata->>'kind' = 'conversation_memory'
            ORDER BY created_at DESC LIMIT 1
        """), {"cid": conversation_id})
        return result.scalar()

    async def save_conversation_summary(self, conversation_id: UUID, summary: str):
        """Guarda el resumen generado por el agente para memoria de largo plazo."""
        await self.save_message(conversation_id, 'system', summary[:6000], metadata={'kind': 'conversation_memory', 'version': 1})
        try:
            r = await self._get_redis()
            await r.set(
                self._cache_key_summary(conversation_id),
                summary,
                ex=settings.REDIS_TTL_SUMMARY
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

    async def acknowledge_map_actions(self, conversation_id, user_id, request_id, applied_indices):
        if any(index < 0 or index > 49 for index in applied_indices):
            raise ValueError("Índice de acción inválido")
        # Store indices against canonical server proposals; do not accept client-supplied actions.
        result = await self.db.execute(text("""
            UPDATE ia_messages m
            SET metadata = coalesce(m.metadata, '{}'::jsonb) || jsonb_build_object('applied_action_indices', CAST(:indices AS jsonb))
            WHERE m.conversation_id = :cid AND m.role = 'assistant'
              AND m.metadata->>'request_id' = :rid
              AND EXISTS (SELECT 1 FROM ia_conversations c WHERE c.id = m.conversation_id AND c.user_id = :uid)
            RETURNING m.id
        """), {"cid": conversation_id, "uid": user_id, "rid": request_id, "indices": json.dumps(sorted(set(applied_indices)))})
        found = result.fetchone() is not None
        if found:
            try:
                redis = await self._get_redis()
                await redis.delete(self._cache_key_history(conversation_id))
            except Exception:
                pass
        return found

    # ── Resto de métodos sin cambios ───────────
    async def get_user_conversations(self, user_id: UUID) -> List[Conversation]:
        stmt = text("""
            SELECT id, title, model_id, created_at, updated_at
            FROM ia_conversations
            WHERE user_id = (:uid)::uuid
            ORDER BY updated_at DESC
        """)
        result = await self.db.execute(stmt, {"uid": str(user_id)})
        conversations = []
        for row in result.mappings().all():
            try:
                conversations.append(Conversation.model_validate(dict(row)))
            except Exception as e:
                self.logger.error(f"Error al procesar conversación: {e}")
        return conversations


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
        check = await self.db.execute(
            text("SELECT id FROM ia_conversations WHERE id = :cid AND user_id = :uid"),
            {"cid": conversation_id, "uid": user_id}
        )
        if not check.fetchone():
            return False

        await self.db.execute(
            text("DELETE FROM ia_messages WHERE conversation_id = :cid"),
            {"cid": conversation_id}
        )
        result = await self.db.execute(
            text("DELETE FROM ia_conversations WHERE id = :cid AND user_id = :uid"),
            {"cid": conversation_id, "uid": user_id}
        )
        await self.db.commit()
        try:
            r = await self._get_redis()
            await r.delete(self._cache_key_history(conversation_id))
            await r.delete(self._cache_key_summary(conversation_id))
        except Exception:
            pass
        return result.rowcount > 0

    async def delete_conversations(self, conversation_ids: List[UUID], user_id: UUID) -> int:
        if not conversation_ids:
            return 0

        result = await self.db.execute(
            text("""
                SELECT id
                FROM ia_conversations
                WHERE user_id = :uid AND id IN :ids
            """).bindparams(bindparam("ids", expanding=True)),
            {"uid": user_id, "ids": conversation_ids}
        )
        owned_ids = [row[0] for row in result.fetchall()]
        if not owned_ids:
            return 0

        await self.db.execute(
            text("DELETE FROM ia_messages WHERE conversation_id IN :ids").bindparams(bindparam("ids", expanding=True)),
            {"ids": owned_ids}
        )
        delete_result = await self.db.execute(
            text("DELETE FROM ia_conversations WHERE user_id = :uid AND id IN :ids").bindparams(bindparam("ids", expanding=True)),
            {"uid": user_id, "ids": owned_ids}
        )
        await self.db.commit()

        try:
            r = await self._get_redis()
            keys = []
            for conv_id in owned_ids:
                keys.append(self._cache_key_history(conv_id))
                keys.append(self._cache_key_summary(conv_id))
            if keys:
                await r.delete(*keys)
        except Exception:
            pass

        return delete_result.rowcount or 0

    # ── Sugerencias de Prompts ─────────────────
    async def get_suggestions(self) -> List[IASuggestion]:
        """Obtiene sugerencias de prompts configuradas en la base de datos."""
        stmt = text("""
            SELECT id, text, category, icon, is_active
            FROM ia_suggestions
            WHERE is_active = true
        """)
        result = await self.db.execute(stmt)
        suggestions = []
        for row in result.mappings().all():
            try:
                suggestions.append(IASuggestion.model_validate(dict(row)))
            except Exception as e:
                self.logger.error(f"Error al procesar sugerencia: {e}")
        return suggestions
