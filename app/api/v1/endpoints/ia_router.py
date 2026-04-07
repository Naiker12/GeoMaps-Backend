import logging
from uuid import UUID
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.ia import ChatRequest, ChatResponse, Conversation, MessageRead, IAModelConfig, IASuggestion
from app.services.ia.agent_service import AgentService
from app.services.ia.history_service import HistoryService
from app.core.exceptions import LLMException, LLMRateLimitException

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/conversations", response_model=List[Conversation])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user_unified)
):
    """Lista las conversaciones del usuario actual."""
    history = HistoryService(db)
    return await history.list_conversations(current_user.id)

@router.get("/conversations/{conversation_id}/messages", response_model=List[MessageRead])
async def get_messages(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user_unified)
):
    """Obtiene los mensajes de una conversación específica."""
    history = HistoryService(db)
    messages = await history.get_messages(conversation_id, current_user.id)
    if messages is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada o acceso denegado")
    return messages

@router.get("/models", response_model=List[IAModelConfig])
async def list_active_models(db: AsyncSession = Depends(get_db)):
    """Retorna la lista de modelos de IA activos."""
    from sqlalchemy import text
    stmt = text("""
        SELECT id, name, provider, model_id, is_active, 
               input_cost_per_1k, output_cost_per_1k, 
               has_function_calling, has_vision, max_context_tokens
        FROM ia_models_config 
        WHERE is_active = true
        ORDER BY provider, name
    """)
    result = await db.execute(stmt)
    return [IAModelConfig(**row) for row in result.mappings().all()]

@router.get("/suggestions", response_model=List[IASuggestion])
async def list_suggestions(db: AsyncSession = Depends(get_db)):
    """Retorna sugerencias de preguntas iniciales."""
    from sqlalchemy import text
    stmt = text("SELECT id, text, category, icon, is_active FROM ia_suggestions WHERE is_active = true ORDER BY created_at ASC")
    result = await db.execute(stmt)
    return [IASuggestion(**row) for row in result.mappings().all()]

@router.post("/chat", response_model=ChatResponse)
async def chat_ia(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user_unified)
):
    """Punto de entrada único para el chat de IA. Delega toda la lógica al AgentService."""
    agent = AgentService(db)
    try:
        return await agent.chat(request, current_user)
    except LLMRateLimitException as e:
        logger.warning(f"Rate limit hit in ChatIA: {str(e)}")
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except LLMException as e:
        logger.error(f"LLM Error in ChatIA: {str(e)}")
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception as e:
        logger.error(f"Critical error in ChatIA: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user_unified)
):
    """Elimina una conversación."""
    history = HistoryService(db)
    success = await history.delete_conversation(conversation_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversación no encontrada o acceso denegado")
    await db.commit()
    return {"status": "success", "message": "Conversación eliminada"}
