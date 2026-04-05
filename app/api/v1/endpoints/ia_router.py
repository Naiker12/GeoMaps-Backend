import logging
import json
import time
from uuid import UUID
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.db.models.user import User
from app.db.session import get_db
from app.core.config import settings
from app.schemas.ia import ChatRequest, ChatResponse, Message, Conversation, MessageRead, IAModelConfig, IASuggestion
from app.services.ia_tools_service import IAToolsService
from app.infrastructure.ia_llm_client import LLMProviderFactory

router = APIRouter()
logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """
Eres GEOMAPS AI, el asistente virtual experto de la plataforma GeoMaps. 
Tu especialidad es el análisis de datos geoespaciales, capas cartográficas y detección satelital.

REGLAS CRÍTICAS DE RESPUESTA:
0. VISUALIZACIÓN AUTOMÁTICA (MANDATORIO): LA PLATAFORMA CARGA LOS PUNTOS AUTOMÁTICAMENTE. ESTÁ ESTRICTAMENTE PROHIBIDO DAR INSTRUCCIONES MANUALES DE IMPORTACIÓN, CARGA DE ARCHIVOS O COPIADO DE GEOJSON. No des pasos a seguir al usuario sobre "cómo verlos", simplemente infórmales que ya están visibles en su mapa.
1. PROHIBICIÓN DE GEOJSON: NO generes bloques de código GeoJSON en tu respuesta de texto. Los datos geográficos se envían de forma invisible a través de las herramientas. Tu respuesta debe ser solo texto informativo legible.
2. HONESTIDAD TOTAL SOBRE DATOS (PRIORIDAD ALTA): Si el usuario pregunta por entidades específicas y tras usar la herramienta 'consultar_predios' no obtienes resultados, DEBES responder: "Lo siento, actualmente no tenemos información disponible en nuestra base de datos sobre [búsqueda] para esta zona específica." No inventes ni supongas.
3. CONTEXTO GEOGRÁFICO: Tienes acceso al área actual que el usuario ve en el mapa (Extent). Úsalo para dar respuestas situacionales.
4. FORMATO: Responde usando una lista de puntos (Markdown). Ejemplo: "* **Nombre**: Descripción". Informa que los puntos ya aparecen resaltados con iconos de estrellas en el mapa.
5. NO INVENTES: Bajo ninguna circunstancia inventes coordenadas o nombres que no aparezcan en los resultados de las herramientas.

ESTADO DEL MAPA:
- Extent Visible: {extent}
- Capas Activas: {layers}
- Usuario: {user_name} ({user_role})
"""

TOOLS_DEFINITION = [
    {
        "type": "function",
        "function": {
            "name": "consultar_predios",
            "description": "Busca lugares, POIs, predios o información geográfica en la base de datos global de GeoMaps.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_texto": {"type": "string", "description": "Nombre del lugar o tipo de entidad a buscar (ej: 'Universidades', 'Calle 10', 'Parques')."},
                    "limit": {"type": "integer", "description": "Máximo de resultados a retornar", "default": 10}
                },
                "required": ["query_texto"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analizar_zona_extent",
            "description": "Analiza geométrica y estadísticamente el área visible (extent) del mapa.",
            "parameters": {
                "type": "object",
                "properties": {
                    "xmin": {"type": "number"}, "ymin": {"type": "number"},
                    "xmax": {"type": "number"}, "ymax": {"type": "number"}
                },
                "required": ["xmin", "ymin", "xmax", "ymax"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_consumo_ia",
            "description": "Consulta el consumo de tokens y costos de IA del usuario.",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]

async def save_msg(db: AsyncSession, conversation_id: UUID, role: str, content: Optional[str], metadata: dict = None, tool_call_id: str = None):
    """Guarda un mensaje en la tabla ia_messages."""
    stmt = text("""
        INSERT INTO ia_messages (conversation_id, role, content, metadata, tool_call_id)
        VALUES ((:cid)::uuid, :role, :content, :meta, :tcid)
    """)
    await db.execute(stmt, {
        "cid": str(conversation_id),
        "role": role,
        "content": content,
        "meta": json.dumps(metadata or {}),
        "tcid": tool_call_id
    })

@router.get("/conversations", response_model=List[Conversation])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user_unified)
):
    """Lista las conversaciones del usuario actual."""
    stmt = text("SELECT id, title, model_id, created_at, updated_at FROM ia_conversations WHERE user_id = (:uid)::uuid ORDER BY updated_at DESC")
    result = await db.execute(stmt, {"uid": str(current_user.id)})
    return [Conversation(**row) for row in result.mappings().all()]

@router.get("/conversations/{conversation_id}/messages", response_model=List[MessageRead])
async def get_conversation_messages(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user_unified)
):
    """Obtiene los mensajes de una conversación específica."""
    # Verificar propiedad
    check = await db.execute(text("SELECT id FROM ia_conversations WHERE id = (:cid)::uuid AND user_id = (:uid)::uuid"), 
                            {"cid": str(conversation_id), "uid": str(current_user.id)})
    if not check.fetchone():
        raise HTTPException(status_code=404, detail="Conversación no encontrada")

    stmt = text("SELECT id, role, content, tool_call_id, metadata, created_at FROM ia_messages WHERE conversation_id = (:cid)::uuid ORDER BY created_at ASC")
    result = await db.execute(stmt, {"cid": str(conversation_id)})
    return [MessageRead(**row) for row in result.mappings().all()]

@router.get("/models", response_model=List[IAModelConfig])
async def list_active_models(
    db: AsyncSession = Depends(get_db)
):
    """Retorna la lista de modelos de IA activos y configurados en la plataforma."""
    stmt = text("""
        SELECT id, name, provider, model_id, is_active, 
               input_cost_per_1k, output_cost_per_1k, 
               has_function_calling, has_vision, max_context_tokens
        FROM ia_models_config 
        WHERE is_active = true
        ORDER BY provider, name
    """)
    result = await db.execute(stmt)
    models = [IAModelConfig(**row) for row in result.mappings().all()]
    
    return models

@router.get("/suggestions", response_model=List[IASuggestion])
async def list_suggestions(
    db: AsyncSession = Depends(get_db)
):
    """Retorna sugerencias de preguntas iniciales para el chat."""
    stmt = text("SELECT id, text, category, icon, is_active FROM ia_suggestions WHERE is_active = true ORDER BY created_at ASC")
    result = await db.execute(stmt)
    return [IASuggestion(**row) for row in result.mappings().all()]

@router.post("/chat", response_model=ChatResponse)
async def chat_ia(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user_unified)
):
    """Orquestador del flujo de IA con persistencia de memoria y auditoría."""
    
    start_time = time.time()
    ia_tools = IAToolsService(db)

    # Límite Diario de Mensajes (Control de Consumo en Pruebas)
    if current_user.role.value != "admin":
        daily_count_stmt = text("""
            SELECT count(*) 
            FROM ia_audit_logs 
            WHERE user_id = (:uid)::uuid 
            AND created_at >= date_trunc('day', now())
            AND status = 'success'
        """)
        daily_count = (await db.execute(daily_count_stmt, {"uid": str(current_user.id)})).scalar() or 0
        if daily_count >= 10:
            raise HTTPException(
                status_code=429, 
                detail="Has alcanzado el límite diario de 10 mensajes para GEOMAPS AI. Tu cuota se reiniciará mañana."
            )
    
    # Resolver Modelo y Configuración
    requested_model = (request.model or "").strip()
    stmt = text("""
        SELECT provider, model_id, is_active, has_function_calling 
        FROM ia_models_config 
        WHERE LOWER(model_id) = LOWER(:mid) OR LOWER(name) = LOWER(:mid) 
        LIMIT 1
    """)
    model_config = (await db.execute(stmt, {"mid": requested_model})).mappings().one_or_none()
    
    # Si no se encuentra el modelo solicitado, intentar fallback al primero activo
    if not model_config:
        # Fallback drástico si la DB está vacía para no romper el servicio
        provider = "openrouter"
        model_id = "google/gemini-2.0-flash-001"
        has_function_calling = True
    else:
        provider = model_config["provider"]
        model_id = model_config["model_id"]
        has_function_calling = model_config["has_function_calling"]

    # Gestionar Conversación (Memoria)
    conversation_id = request.conversation_id
    if not conversation_id:
        # Crear nueva conversación
        new_conv = await db.execute(text("""
            INSERT INTO ia_conversations (user_id, model_id, title)
            VALUES ((:uid)::uuid, :mid, :title) RETURNING id
        """), {
            "uid": str(current_user.id),
            "mid": model_id,
            "title": request.message[:60] + "..." if len(request.message) > 60 else request.message
        })
        conversation_id = new_conv.scalar()
    
    # Guardar mensaje del usuario
    await save_msg(db, conversation_id, "user", request.message)

    # Preparar LLM Client
    api_key = settings.OPENROUTER_API_KEY
    if not api_key:
        raise HTTPException(status_code=500, detail="Configuración de OpenRouter no encontrada.")

    client = LLMProviderFactory.create(provider, api_key, model_id)

    # Construir Contexto y Mensajes
    extent = request.context_mapa.get("extent") if request.context_mapa else "No disponible"
    layers = request.context_mapa.get("layers") if request.context_mapa else "No disponible"
    
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        user_name=current_user.full_name or "Usuario",
        user_role=current_user.role.value,
        extent=json.dumps(extent),
        layers=json.dumps(layers)
    )

    messages = [Message(role="system", content=system_prompt)]
    
    # Si viene historial del frontend, lo usamos. Si no, podríamos cargarlo aquí del DB
    # Por ahora confiamos en el envío del historial del frontend para eficiencia
    if request.historial:
        messages.extend(request.historial)
    else:
        # Cargar últimos 10 mensajes del DB si es una conversación existente sin historial enviado
        db_messages = await get_conversation_messages(conversation_id, db, current_user)
        # Convertir a formato Message (excluyendo el actual que acabamos de guardar)
        for m in db_messages[:-1]:
            messages.append(Message(role=m.role, content=m.content, tool_call_id=m.tool_call_id))

    messages.append(Message(role="user", content=request.message))

    # Ejecución del Ciclo LLM (Reintentos para Function Calling)
    total_tokens_in = 0
    total_tokens_out = 0
    tools_executed = []
    max_iterations = 5

    final_content = ""

    for _ in range(max_iterations):
        tools_to_use = TOOLS_DEFINITION if has_function_calling else None
        response_data = await client.chat_complete(messages, tools=tools_to_use)
        
        if response_data["status"] == "error":
            raise HTTPException(status_code=502, detail=response_data["error_message"])
        
        total_tokens_in += response_data["tokens_input"]
        total_tokens_out += response_data["tokens_output"]
        
        resp_msg = response_data["message"]
        tool_calls = resp_msg.get("tool_calls")
        content = resp_msg.get("content")

        # Guardar mensaje del asistente (venga con texto o con tool_calls)
        await save_msg(db, conversation_id, "assistant", content, metadata={"tool_calls": tool_calls})

        messages.append(Message(role="assistant", content=content, tool_calls=tool_calls))

        if not tool_calls:
            final_content = content
            break
        
        # Procesar herramientas
        for tc in tool_calls:
            func_name = tc["function"]["name"]
            req_args = json.loads(tc["function"]["arguments"])
            
            result = None
            try:
                if func_name == "consultar_predios":
                    result = await ia_tools.consultar_predios(**req_args)
                elif func_name == "analizar_zona_extent":
                    result = await ia_tools.analizar_zona_extent(**req_args)
                elif func_name == "obtener_consumo_ia":
                    result = await ia_tools.obtener_consumo_ia(str(current_user.id))
            except Exception as e:
                result = {"error": str(e)}

            tools_executed.append({"id": tc["id"], "tool": func_name, "params": req_args, "result": result})
            
            # Guardar respuesta de herramienta
            await save_msg(db, conversation_id, "tool", json.dumps(result), tool_call_id=tc["id"])
            messages.append(Message(role="tool", tool_call_id=tc["id"], content=json.dumps(result)))
    
    # Auditoría y Persistencia Final
    latency_ms = int((time.time() - start_time) * 1000)
    
    # Calcular costo real desde la DB
    rates = await db.execute(text("SELECT input_cost_per_1k, output_cost_per_1k FROM ia_models_config WHERE model_id = :mid"), {"mid": model_id})
    rate_row = rates.mappings().one_or_none()
    
    cost = 0.0
    if rate_row:
        cost = (total_tokens_in * rate_row["input_cost_per_1k"] / 1000) + (total_tokens_out * rate_row["output_cost_per_1k"] / 1000)

    # Actualizar timestamp de la conversación
    await db.execute(text("UPDATE ia_conversations SET updated_at = now() WHERE id = (:cid)::uuid"), {"cid": str(conversation_id)})
    
    # Registro en log de auditoría
    audit_stmt = text("""
        INSERT INTO ia_audit_logs (user_id, model, tokens_input, tokens_output, cost, latency_ms, tools_called, status)
        VALUES ((:uid)::uuid, :model, :tin, :tout, :cost, :lat, :tools, 'success')
    """)
    await db.execute(audit_stmt, {
        "uid": str(current_user.id),
        "model": model_id,
        "tin": total_tokens_in,
        "tout": total_tokens_out,
        "cost": cost,
        "lat": latency_ms,
        "tools": json.dumps(tools_executed)
    })
    
    await db.commit()

    return ChatResponse(
        message=final_content or "Análisis completado.",
        conversation_id=conversation_id,
        model_used=model_id,
        tokens_input=total_tokens_in,
        tokens_output=total_tokens_out,
        cost=cost,
        latency_ms=latency_ms,
        tools_called=tools_executed,
        tools_called_raw=resp_msg.get('tool_calls', [])
    )

@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user_unified)
):
    """Elimina una conversación y sus mensajes asociados."""
    # Verificar propiedad
    stmt = text("SELECT user_id FROM ia_conversations WHERE id = (:cid)::uuid")
    result = await db.execute(stmt, {"cid": conversation_id})
    owner_id = result.scalar()
    
    if not owner_id:
        raise HTTPException(status_code=404, detail="Conversación no encontrada.")
    if str(owner_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="No tienes permiso para eliminar esta conversación.")
        
    # Eliminar mensajes primero (aunque ON DELETE CASCADE debería estar en la DB)
    await db.execute(text("DELETE FROM ia_messages WHERE conversation_id = (:cid)::uuid"), {"cid": conversation_id})
    await db.execute(text("DELETE FROM ia_conversations WHERE id = (:cid)::uuid"), {"cid": conversation_id})
    
    await db.commit()
    return {"status": "success", "message": "Conversación eliminada."}
