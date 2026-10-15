import asyncio
import anyio
import json
import logging
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Any
from uuid import UUID
from app.db.session import get_db
from app.services.ia.agent_service import AgentService
from app.services.ia.history_service import HistoryService
from app.services.ia.usage_service import UsageService
from app.services.ia.stt_service import stt_service
from app.schemas.ia import ChatRequest, ChatResponse, MessageRead, Conversation, IASuggestion, IAModelConfig, IAUsageResponse, DeleteConversationsRequest, MapActionAcknowledgement
from app.api.deps import get_current_active_user
from app.db.models.user import User

from app.core.exceptions import LLMException
from app.services.ia.geo_context import resolve_geo_context

router = APIRouter()
logger = logging.getLogger(__name__)


def _validate_geo_context(request: ChatRequest) -> None:
    try:
        resolve_geo_context(request.context_mapa, request.geo_context)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc

@router.post("/chat", response_model=ChatResponse)
async def chat_with_ia(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Endpoint sincrónico para chatear con la IA (Retrocompatibilidad)."""
    _validate_geo_context(request)
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

async def _stream_with_limits(agent, request, user):
    try:
        async with asyncio.timeout(160):
            async for event in agent.chat_stream(request, user):
                if json.loads(event[6:]).get('type') == 'error':
                    await agent.record_stream_failure('error')
                yield event
    except asyncio.CancelledError:
        with anyio.CancelScope(shield=True):
            try: await asyncio.wait_for(agent.record_stream_failure("cancelled"), timeout=5)
            except Exception: logger.warning("No se pudo guardar la respuesta interrumpida")
        raise
    except TimeoutError:
        try: await agent.record_stream_failure("error")
        except Exception: logger.warning("No se pudo registrar el tiempo agotado")
        yield f"data: {json.dumps({'type': 'error', 'content': 'Se alcanzó el límite de tiempo. Reduce el alcance de la consulta.'})}\n\n"
    except Exception:
        logger.exception("Falló el flujo de IA")
        try: await agent.record_stream_failure("error")
        except Exception: logger.warning("No se pudo registrar el flujo fallido")
        yield f"data: {json.dumps({'type': 'error', 'content': 'No se pudo completar la respuesta. La parte recibida se conserva.'})}\n\n"


@router.post("/chat/stream")
async def chat_with_ia_stream(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Endpoint SSE para chatear con la IA con efecto máquina de escribir."""
    _validate_geo_context(request)
    usage_service = UsageService(db)
    usage = await usage_service.get_user_usage(current_user.id)
    
    if usage["is_blocked"]:
        raise HTTPException(
            status_code=429, 
            detail=f"Límite de mensajes alcanzado. Intenta de nuevo en {int(usage['remaining_seconds']/60)} minutos."
        )

    agent = AgentService(db)
    return StreamingResponse(
        _stream_with_limits(agent, request, current_user),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
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


@router.post("/conversations/{conversation_id}/map-actions/ack")
async def acknowledge_map_actions(conversation_id: UUID, acknowledgement: MapActionAcknowledgement,
                                  db: AsyncSession = Depends(get_db),
                                  current_user: User = Depends(get_current_active_user)):
    try:
        found = await HistoryService(db).acknowledge_map_actions(conversation_id, current_user.id,
                    acknowledgement.request_id, acknowledgement.applied_indices)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    if not found:
        raise HTTPException(404, detail="No se encontró la respuesta en tu conversación")
    await db.commit()
    return {"success": True}

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


@router.post("/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    language: str = Form("es-CO"),
    current_user: User = Depends(get_current_active_user),
):
    """Transcribe audio from browsers without native SpeechRecognition support."""
    try:
        audio_bytes = await audio.read()
        text = await stt_service.transcribe(
            audio_bytes,
            language=language,
            mime_type=audio.content_type,
        )
        return {"text": text, "language": language}
    except Exception as e:
        logger.error("Error transcribiendo audio: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="No se pudo transcribir el audio.")
