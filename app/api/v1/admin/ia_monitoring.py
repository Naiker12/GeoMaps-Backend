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
    
    # 1. Resumen General
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

    # 2. Consumo por Modelo
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

    # 3. Datos Históricos (para gráficas)
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
    """Lista detallada de logs de auditoría de IA."""
    stmt = text("""
        SELECT a.*, u.full_name as user_name
        FROM ia_audit_logs a
        LEFT JOIN users u ON a.user_id = u.id
        ORDER BY a.created_at DESC
        LIMIT :limit OFFSET :offset
    """)
    result = await db.execute(stmt, {"limit": limit, "offset": offset})
    return result.mappings().all()

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
