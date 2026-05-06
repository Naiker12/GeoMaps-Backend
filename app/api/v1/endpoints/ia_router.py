import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Any
from uuid import UUID
from app.db.session import get_db
from app.services.ia.agent_service import AgentService
from app.services.ia.history_service import HistoryService
from app.services.ia.usage_service import UsageService
from app.schemas.ia import ChatRequest, ChatResponse, MessageRead, Conversation, IASuggestion, IAModelConfig, IAUsageResponse, DeleteConversationsRequest
from app.api.deps import get_current_active_user
from app.db.models.user import User

from app.core.exceptions import LLMException

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/chat", response_model=ChatResponse)
async def chat_with_ia(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Endpoint sincrónico para chatear con la IA (Retrocompatibilidad)."""
    usage_service = UsageService(db)
    usage = await usage_service.get_user_usage(current_user.id)
    
    if usage["is_blocked"]:
        raise HTTPException(
            status_code=429, 
            detail=f"Has alcanzado el límite de {usage['limit']} mensajes. "
                   f"Podrás enviar más en aproximadamente {int(usage['remaining_seconds']/60)} minutos."
        )

    agent = AgentService(db)
    try:
        return await agent.chat(request, current_user)
    except LLMException as e:
        # Los errores de LLMException ya vienen con un mensaje amigable del proveedor
        logger.warning(f"Error controlado de IA: {str(e)}")
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except Exception as e:
        logger.error(f"Error inesperado en chat_with_ia: {str(e)}", exc_info=True)
        # Para errores desconocidos, usamos un mensaje genérico seguro
        error_detail = "Lo siento, ocurrió un error interno al procesar tu solicitud. Por favor intenta de nuevo más tarde."
        raise HTTPException(status_code=500, detail=error_detail)

@router.post("/chat/stream")
async def chat_with_ia_stream(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Endpoint SSE para chatear con la IA con efecto máquina de escribir."""
    usage_service = UsageService(db)
    usage = await usage_service.get_user_usage(current_user.id)
    
    if usage["is_blocked"]:
        raise HTTPException(
            status_code=429, 
            detail=f"Límite de mensajes alcanzado. Intenta de nuevo en {int(usage['remaining_seconds']/60)} minutos."
        )

    agent = AgentService(db)
    return StreamingResponse(
        agent.chat_stream(request, current_user),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream",
        }
    )

@router.get("/models", response_model=List[IAModelConfig])
async def get_available_models(
    db: AsyncSession = Depends(get_db)
):
    """Obtiene la lista de modelos de IA disponibles."""
    agent = AgentService(db)
    return await agent.get_available_models()

@router.get("/conversations", response_model=List[Conversation])
async def get_chat_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Obtiene la lista de conversaciones del usuario."""
    history_service = HistoryService(db)
    return await history_service.get_user_conversations(current_user.id)

@router.get("/conversations/{conversation_id}/messages", response_model=List[MessageRead])
async def get_conversation_messages(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Obtiene los mensajes de una conversación específica."""
    history_service = HistoryService(db)
    return await history_service.get_messages(conversation_id, current_user.id)

@router.delete("/conversations")
async def delete_conversations(
    request: DeleteConversationsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Elimina varias conversaciones del usuario actual."""
    if not request.conversation_ids:
        raise HTTPException(status_code=400, detail="No hay conversaciones seleccionadas")

    history_service = HistoryService(db)
    deleted_count = await history_service.delete_conversations(
        request.conversation_ids,
        current_user.id
    )
    return {
        "status": "success",
        "deleted_count": deleted_count,
        "message": f"{deleted_count} conversaciones eliminadas"
    }

@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Elimina una conversación y sus mensajes."""
    history_service = HistoryService(db)
    deleted = await history_service.delete_conversation(conversation_id, current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversacion no encontrada")
    return {"status": "success", "message": "Conversación eliminada"}

@router.get("/suggestions", response_model=List[IASuggestion])
async def get_ia_suggestions(
    db: AsyncSession = Depends(get_db)
):
    """Obtiene sugerencias de prompts para el chat de IA."""
    history_service = HistoryService(db)
    return await history_service.get_suggestions()

@router.get("/usage", response_model=IAUsageResponse)
async def get_ia_usage(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Obtiene el consumo actual de mensajes del usuario."""
    usage_service = UsageService(db)
    return await usage_service.get_user_usage(current_user.id)
