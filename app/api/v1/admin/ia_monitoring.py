from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from uuid import UUID

from app.api import deps
from app.db.session import get_db
from app.schemas.ia import IAModelConfig

router = APIRouter()

@router.get("/stats")
async def get_ia_stats(
    days: int = Query(7),
    db: AsyncSession = Depends(get_db)
):
    """Obtiene estadísticas agregadas de consumo de IA para el Dashboard."""
    
    # Resumen General de Consumo
    summary_stmt = text("""
        SELECT 
            COUNT(*) as total_requests,
            SUM(tokens_input + tokens_output) as total_tokens,
            SUM(cost) as total_cost,
            AVG(latency_ms) as avg_latency
        FROM ia_audit_logs
        WHERE created_at >= NOW() - INTERVAL '1 day' * :days
    """)
    summary = (await db.execute(summary_stmt, {"days": days})).mappings().one()

    # Desglose de Consumo por Modelo
    model_usage_stmt = text("""
        SELECT 
            model as model_id, 
            COUNT(*) as requests,
            SUM(tokens_input + tokens_output) as tokens,
            SUM(cost) as cost
        FROM ia_audit_logs
        WHERE created_at >= NOW() - INTERVAL '1 day' * :days
        GROUP BY model
        ORDER BY requests DESC
    """)
    models = (await db.execute(model_usage_stmt, {"days": days})).mappings().all()

    # Histórico de Actividad Temporal
    history_stmt = text("""
        SELECT 
            DATE_TRUNC('day', created_at) as date,
            COUNT(*) as requests,
            SUM(cost) as cost
        FROM ia_audit_logs
        WHERE created_at >= NOW() - INTERVAL '1 day' * :days
        GROUP BY date
        ORDER BY date ASC
    """)
    history = (await db.execute(history_stmt, {"days": days})).mappings().all()

    return {
        "summary": summary,
        "models": models,
        "history": [dict(h) for h in history]
    }

@router.get("/audit-logs")
async def get_ia_audit_logs(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    """Lista detallada de logs de auditoría de IA con soporte para paginación."""
    
    # Obtener el conteo total de registros
    count_stmt = text("SELECT COUNT(*) FROM ia_audit_logs")
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # Obtener el listado paginado
    stmt = text("""
        SELECT a.*, u.full_name as user_name
        FROM ia_audit_logs a
        LEFT JOIN users u ON a.user_id = u.id
        ORDER BY a.created_at DESC
        LIMIT :limit OFFSET :offset
    """)
    result = await db.execute(stmt, {"limit": limit, "offset": offset})
    logs = result.mappings().all()

    return {
        "items": [dict(log) for log in logs],
        "total": total
    }

@router.get("/audit-logs/{log_id}/details")
async def get_audit_log_details(
    log_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Obtiene los mensajes detallados de la conversación vinculada a un log de auditoría."""
    
    # 1. Obtener el conversation_id del log
    log_stmt = text("SELECT conversation_id FROM ia_audit_logs WHERE id = :lid")
    log_res = await db.execute(log_stmt, {"lid": str(log_id)})
    log = log_res.mappings().first()
    
    if not log or not log["conversation_id"]:
        raise HTTPException(status_code=404, detail="Log o conversación no encontrados")
    
    # 2. Obtener los mensajes de ia_messages
    msg_stmt = text("""
        SELECT role, content, metadata, created_at 
        FROM ia_messages 
        WHERE conversation_id = :cid 
        ORDER BY created_at ASC
    """)
    messages_res = await db.execute(msg_stmt, {"cid": log["conversation_id"]})
    messages = messages_res.mappings().all()
    
    return [dict(m) for m in messages]

@router.get("/models", response_model=List[IAModelConfig])
async def list_all_models(db: AsyncSession = Depends(get_db)):
    """Lista todos los modelos configurados (incluyendo inactivos)."""
    stmt = text("SELECT * FROM ia_models_config ORDER BY provider, name")
    result = await db.execute(stmt)
    return [IAModelConfig(**row) for row in result.mappings().all()]

@router.post("/models", response_model=IAModelConfig)
async def create_model_config(
    model: IAModelConfig,
    db: AsyncSession = Depends(get_db)
):
    """Crea una nueva configuración de modelo."""
    stmt = text("""
        INSERT INTO ia_models_config (
            name, provider, model_id, is_active, 
            input_cost_per_1k, output_cost_per_1k, 
            has_function_calling, has_vision, max_context_tokens
        ) VALUES (
            :name, :provider, :model_id, :is_active, 
            :input_cost_per_1k, :output_cost_per_1k, 
            :has_function_calling, :has_vision, :max_context_tokens
        ) RETURNING *
    """)
    
    result = await db.execute(stmt, model.model_dump(exclude={"id"}))
    await db.commit()
    
    row = result.mappings().one()
    return IAModelConfig(**row)

@router.patch("/models/{model_uuid}")
async def update_model_config(
    model_uuid: UUID,
    updates: Dict[str, Any],
    db: AsyncSession = Depends(get_db)
):
    """Actualiza la configuración o estado de un modelo."""
    if not updates:
        raise HTTPException(status_code=400, detail="No se enviaron campos para actualizar")
    
    set_clause = ", ".join([f"{k} = :{k}" for k in updates.keys()])
    stmt = text(f"UPDATE ia_models_config SET {set_clause} WHERE id = :mid RETURNING id")
    params = {**updates, "mid": str(model_uuid)}
    
    result = await db.execute(stmt, params)
    await db.commit()
    
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Modelo no encontrado")
    
    return {"status": "updated"}

@router.delete("/models/{model_uuid}")
async def delete_model_config(
    model_uuid: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Elimina un modelo de la configuración."""
    stmt = text("DELETE FROM ia_models_config WHERE id = :mid RETURNING id")
    result = await db.execute(stmt, {"mid": str(model_uuid)})
    await db.commit()
    
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Modelo no encontrado")
    
    return {"status": "deleted"}

@router.delete("/audit-logs/clear")
async def clear_all_ia_data(db: AsyncSession = Depends(get_db)):
    """Elimina todos los registros de auditoría, mensajes y conversaciones de IA."""
    try:
        # El orden es importante por las claves foráneas
        await db.execute(text("DELETE FROM ia_audit_logs"))
        await db.execute(text("DELETE FROM ia_messages"))
        await db.execute(text("DELETE FROM ia_conversations"))
        await db.commit()
        return {"status": "success", "message": "Historial de IA limpiado correctamente"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al limpiar historial: {str(e)}")
