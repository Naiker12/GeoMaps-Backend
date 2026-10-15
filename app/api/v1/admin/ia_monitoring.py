import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from uuid import UUID

from app.db.session import get_db
from app.schemas.ia import IAModelConfig
from app.services.ia.provider_connections import ConnectionRequest, ConnectModelRequest, discover_models, encrypt_key, validate_url

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/stats")
async def get_ia_stats(days: int = Query(7), db: AsyncSession = Depends(get_db)):
    """Obtiene estadísticas agregadas de consumo de IA para el Dashboard."""
    logger.info(f"Obteniendo estadísticas de IA para los últimos {days} días")

    try:
        summary_stmt = text("""
            SELECT
                COUNT(*) as total_requests,
                COALESCE(SUM(tokens_input + tokens_output), 0) as total_tokens,
                COALESCE(SUM(cost), 0) as total_cost,
                COALESCE(AVG(latency_ms), 0) as avg_latency
            FROM ia_audit_logs
            WHERE created_at >= NOW() - INTERVAL '1 day' * :days
        """)
        summary_res = await db.execute(summary_stmt, {"days": days})
        # Mappings().one() siempre devuelve una fila para agregados sin GROUP BY
        summary_row = summary_res.mappings().one()
        summary = {
            "total_requests": summary_row["total_requests"] or 0,
            "total_tokens": int(summary_row["total_tokens"] or 0),
            "total_cost": float(summary_row["total_cost"] or 0),
            "avg_latency": float(summary_row["avg_latency"] or 0),
        }

        # Desglose de Consumo por Modelo
        model_usage_stmt = text("""
            SELECT
                model as model_id,
                COUNT(*) as requests,
                COALESCE(SUM(tokens_input + tokens_output), 0) as tokens,
                COALESCE(SUM(cost), 0) as cost
            FROM ia_audit_logs
            WHERE created_at >= NOW() - INTERVAL '1 day' * :days
            GROUP BY model
            ORDER BY requests DESC
        """)
        models_res = await db.execute(model_usage_stmt, {"days": days})
        models = []
        for r in models_res.mappings().all():
            models.append(
                {
                    "model_id": r["model_id"],
                    "requests": r["requests"] or 0,
                    "tokens": int(r["tokens"] or 0),
                    "cost": float(r["cost"] or 0),
                }
            )

        # Histórico de Actividad Temporal
        history_stmt = text("""
            SELECT
                DATE_TRUNC('hour', created_at) as timestamp,
                COUNT(*) as requests,
                COALESCE(SUM(tokens_input + tokens_output), 0) as tokens,
                COALESCE(SUM(cost), 0) as cost
            FROM ia_audit_logs
            WHERE created_at >= NOW() - INTERVAL '1 day' * :days
            GROUP BY 1
            ORDER BY 1 ASC
        """)
        history_res = await db.execute(history_stmt, {"days": days})
        history = []
        for h in history_res.mappings().all():
            history.append(
                {
                    "timestamp": h["timestamp"].isoformat() if h["timestamp"] else None,
                    "requests": h["requests"] or 0,
                    "tokens": int(h["tokens"] or 0),
                    "cost": float(h["cost"] or 0),
                }
            )

        return {"summary": summary, "models": models, "history": history}
    except Exception as e:
        logger.error(f"Error en get_ia_stats: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Error interno al procesar estadísticas"
        )


@router.get("/audit-logs")
async def get_ia_audit_logs(
    limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db)
):
    """Lista logs de auditoría agrupados por usuario con totales de tokens."""
    logger.info(f"Obteniendo logs de auditoría de IA (limit={limit}, offset={offset})")

    try:
        count_stmt = text("SELECT COUNT(DISTINCT user_id) FROM ia_audit_logs")
        total_result = await db.execute(count_stmt)
        total = total_result.scalar() or 0

        # Eliminamos MODE() temporalmente por si causa problemas en el driver Windows
        stmt = text("""
            SELECT
                a.user_id,
                u.full_name as user_name,
                COUNT(*) as total_requests,
                COALESCE(SUM(a.tokens_input), 0) as total_tokens_in,
                COALESCE(SUM(a.tokens_output), 0) as total_tokens_out,
                COALESCE(SUM(a.cost), 0) as total_cost,
                COALESCE(AVG(a.latency_ms), 0) as avg_latency,
                MAX(a.created_at) as last_activity,
                COUNT(CASE WHEN a.status = 'success' THEN 1 END) as success_count,
                COUNT(CASE WHEN a.status != 'success' THEN 1 END) as error_count
            FROM ia_audit_logs a
            LEFT JOIN users u ON a.user_id = u.id
            GROUP BY a.user_id, u.full_name
            ORDER BY MAX(a.created_at) DESC
            LIMIT :limit OFFSET :offset
        """)
        result = await db.execute(stmt, {"limit": limit, "offset": offset})
        logs = []
        for r in result.mappings().all():
            logs.append(
                {
                    "user_id": str(r["user_id"]) if r["user_id"] else None,
                    "user_name": r["user_name"] or "Usuario Anónimo",
                    "total_requests": r["total_requests"] or 0,
                    "total_tokens_in": int(r["total_tokens_in"] or 0),
                    "total_tokens_out": int(r["total_tokens_out"] or 0),
                    "total_cost": float(r["total_cost"] or 0),
                    "avg_latency": float(r["avg_latency"] or 0),
                    "last_activity": r["last_activity"].isoformat()
                    if r["last_activity"]
                    else None,
                    "success_count": r["success_count"] or 0,
                    "error_count": r["error_count"] or 0,
                    "most_used_model": "N/A",  # Simplificado
                }
            )

        return {"items": logs, "total": total}
    except Exception as e:
        logger.error(f"Error en get_ia_audit_logs: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error interno al listar logs")


@router.get("/audit-logs/user/{user_id}")
async def get_user_audit_detail(user_id: UUID, db: AsyncSession = Depends(get_db)):
    """Obtiene el detalle de consumo de IA de un usuario específico."""

    # Consumo diario de tokens (para gráfico)
    daily_stmt = text("""
        SELECT
            DATE_TRUNC('day', created_at) as date,
            SUM(tokens_input) as tokens_in,
            SUM(tokens_output) as tokens_out,
            SUM(cost) as cost,
            COUNT(*) as requests
        FROM ia_audit_logs
        WHERE user_id = :uid
        GROUP BY date
        ORDER BY date DESC
        LIMIT 14
    """)
    daily = (await db.execute(daily_stmt, {"uid": str(user_id)})).mappings().all()

    # Logs individuales recientes
    logs_stmt = text("""
        SELECT id, model, tokens_input, tokens_output, cost, status, latency_ms, created_at, conversation_id
        FROM ia_audit_logs
        WHERE user_id = :uid
        ORDER BY created_at DESC
        LIMIT 20
    """)
    logs = (await db.execute(logs_stmt, {"uid": str(user_id)})).mappings().all()

    # Desglose por modelo
    models_stmt = text("""
        SELECT
            model,
            COUNT(*) as requests,
            SUM(tokens_input + tokens_output) as total_tokens,
            SUM(cost) as total_cost
        FROM ia_audit_logs
        WHERE user_id = :uid
        GROUP BY model
        ORDER BY total_tokens DESC
    """)
    models = (await db.execute(models_stmt, {"uid": str(user_id)})).mappings().all()

    return {
        "daily": [dict(d) for d in reversed(list(daily))],
        "logs": [dict(l) for l in logs],
        "models": [dict(m) for m in models],
    }


@router.get("/audit-logs/{log_id}/details")
async def get_audit_log_details(log_id: UUID, db: AsyncSession = Depends(get_db)):
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
    """Lista todas las configuraciones de modelos de IA."""
    logger.info("Listando configuraciones de modelos de IA")
    try:
        stmt = (
            select(text("*"))
            .select_from(text("ia_models_config"))
            .order_by(text("name ASC"))
        )
        result = await db.execute(stmt)
        models = []
        for row in result.mappings().all():
            try:
                # Convertimos tipos Decimal y manejamos nulos
                d = dict(row)
                if d.get("input_cost_per_1k") is not None:
                    d["input_cost_per_1k"] = float(d["input_cost_per_1k"])
                if d.get("output_cost_per_1k") is not None:
                    d["output_cost_per_1k"] = float(d["output_cost_per_1k"])

                models.append(IAModelConfig.model_validate(d))
            except Exception as ser_err:
                logger.warning(
                    f"Error serializando modelo {row.get('name')}: {ser_err}"
                )
                # Intentamos añadirlo igual si tiene lo mínimo
                if d.get("name") and d.get("model_id"):
                    models.append(
                        IAModelConfig(
                            id=d.get("id"),
                            name=d["name"],
                            provider=d.get("provider", "unknown"),
                            model_id=d["model_id"],
                            is_active=d.get("is_active", True),
                        )
                    )
        return models
    except Exception as e:
        logger.error(f"Error en list_all_models: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error al listar modelos")


@router.post("/models", response_model=IAModelConfig)
async def create_model_config(model: IAModelConfig, db: AsyncSession = Depends(get_db)):
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
    model_uuid: UUID, updates: Dict[str, Any], db: AsyncSession = Depends(get_db)
):
    """Actualiza la configuración o estado de un modelo."""
    allowed = {"name", "is_active", "input_cost_per_1k", "output_cost_per_1k", "has_function_calling", "has_vision", "max_context_tokens"}
    if set(updates) - allowed:
        raise HTTPException(422, "Campos de actualización no permitidos.")
    if updates.get("is_active") is False:
        row = (await db.execute(text("SELECT is_default FROM ia_models_config WHERE id = :mid FOR UPDATE"), {"mid": str(model_uuid)})).mappings().first()
        if row and row["is_default"]:
            raise HTTPException(409, "Selecciona otro modelo predeterminado antes de desactivar este.")
    if not updates:
        raise HTTPException(
            status_code=400, detail="No se enviaron campos para actualizar"
        )

    set_clause = ", ".join([f"{k} = :{k}" for k in updates.keys()])
    stmt = text(
        f"UPDATE ia_models_config SET {set_clause} WHERE id = :mid RETURNING id"
    )
    params = {**updates, "mid": str(model_uuid)}

    result = await db.execute(stmt, params)
    await db.commit()

    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Modelo no encontrado")

    return {"status": "updated"}


@router.delete("/models/{model_uuid}")
async def delete_model_config(model_uuid: UUID, db: AsyncSession = Depends(get_db)):
    """Elimina un modelo de la configuración."""
    row = (await db.execute(text("SELECT is_default FROM ia_models_config WHERE id = :mid FOR UPDATE"), {"mid": str(model_uuid)})).mappings().first()
    if row and row["is_default"]:
        raise HTTPException(409, "Selecciona otro modelo predeterminado antes de eliminar este.")
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
        return {
            "status": "success",
            "message": "Historial de IA limpiado correctamente",
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Error al limpiar historial: {str(e)}"
        )
@router.get('/providers')
async def list_providers():
    from app.services.ia.provider_connections import PROVIDERS
    return PROVIDERS


@router.post('/providers/discover')
async def discover_provider_models(connection: ConnectionRequest):
    return {'models': await discover_models(connection)}


@router.post('/models/connect', response_model=IAModelConfig)
async def connect_provider_model(connection: ConnectModelRequest, db: AsyncSession = Depends(get_db)):
    available = await discover_models(connection)
    selected = next((model for model in available if model['id'] == connection.model_id), None)
    if selected is None:
        raise HTTPException(422, 'Selecciona un modelo disponible en el proveedor.')
    encrypted = encrypt_key(connection.api_key.get_secret_value().strip())
    await db.execute(text('SELECT pg_advisory_xact_lock(674312)'))
    existing = (await db.execute(text('SELECT id, is_default FROM ia_models_config WHERE provider = :provider AND model_id = :model_id FOR UPDATE'), {'provider': connection.provider, 'model_id': connection.model_id})).mappings().first()
    make_default = connection.is_default or bool(existing and existing['is_default'])
    if make_default:
        await db.execute(text('UPDATE ia_models_config SET is_default = false WHERE is_default = true'))
    if existing:
        result = await db.execute(text('UPDATE ia_models_config SET name=:name, base_url=:url, api_key_encrypted=:key, is_active=true, is_default=:default, has_function_calling=coalesce(CAST(:tools AS boolean),has_function_calling), has_vision=coalesce(CAST(:vision AS boolean),has_vision), max_context_tokens=coalesce(CAST(:context AS integer),max_context_tokens) WHERE id=:id RETURNING *'), {'name': connection.name, 'url': validate_url(connection.provider, connection.base_url), 'key': encrypted, 'default': make_default, 'id': existing['id'], 'tools': selected.get('has_function_calling'), 'vision': selected.get('has_vision'), 'context': selected.get('max_context_tokens')})
        row = result.mappings().one()
        await db.commit()
        return IAModelConfig.model_validate(dict(row))
    result = await db.execute(text('''
        INSERT INTO ia_models_config (name, provider, model_id, is_active, base_url, api_key_encrypted, is_default, has_function_calling, has_vision, max_context_tokens, input_cost_per_1k, output_cost_per_1k)
        VALUES (:name, :provider, :model_id, true, :base_url, :api_key_encrypted, :is_default, :tools, :vision, :context, 0, 0)
        RETURNING *
    '''), dict(name=connection.name.strip(), provider=connection.provider, model_id=connection.model_id,
               base_url=validate_url(connection.provider, connection.base_url), api_key_encrypted=encrypted, is_default=make_default, tools=selected.get('has_function_calling') or False, vision=selected.get('has_vision') or False, context=selected.get('max_context_tokens') or 4096))
    row = result.mappings().one()
    await db.commit()
    return IAModelConfig.model_validate(dict(row))


@router.post('/models/{model_uuid}/default')
async def set_default_model(model_uuid: UUID, db: AsyncSession = Depends(get_db)):
    await db.execute(text('SELECT pg_advisory_xact_lock(674312)'))
    row = (await db.execute(text('SELECT is_active FROM ia_models_config WHERE id = :mid FOR UPDATE'), {'mid': str(model_uuid)})).mappings().first()
    if not row:
        raise HTTPException(404, 'Modelo no encontrado.')
    if not row['is_active']:
        raise HTTPException(409, 'Activa el modelo antes de seleccionarlo como predeterminado.')
    await db.execute(text('UPDATE ia_models_config SET is_default = false WHERE is_default = true'))
    await db.execute(text('UPDATE ia_models_config SET is_default = true WHERE id = :mid'), {'mid': str(model_uuid)})
    await db.commit()
    return {'status': 'updated'}
