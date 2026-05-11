"""
GeoMaps — Router de Reportes IA.
Endpoints REST para generar, consultar y descargar reportes PDF profesionales.
"""
import logging
import os
import json
import uuid
from datetime import datetime
from typing import Dict, Any
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.api.deps import get_current_active_user
from app.db.models.user import User
from app.services.report.report_engine import ReportEngine
from app.services.export.typst_service import TypstPDFService
from app.schemas.report_schemas import (
    ReportRequest,
    ReportGenerateResponse,
    ReportStatusResponse,
)
from app.core.config import settings
import redis.asyncio as redis

router = APIRouter()
logger = logging.getLogger(__name__)

# Configuración de Redis para el estado de los reportes
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
REPORT_TTL = 3600  # 1 hora


@router.post("/generate", response_model=ReportGenerateResponse)
async def generate_report(
    request: ReportRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Genera un reporte completo.
    """
    report_id = str(uuid.uuid4())
    
    # Inicializar estado en Redis
    report_status = {
        "id": report_id,
        "status": "processing",
        "progress": 10,
        "type": "custom",
        "created_at": datetime.now().isoformat(),
    }
    await redis_client.setex(f"report:{report_id}", REPORT_TTL, json.dumps(report_status))

    # Iniciar generación en segundo plano
    background_tasks.add_task(
        _generate_pdf_background,
        report_id,
        request,
        db,
        str(current_user.id),
    )

    return ReportGenerateResponse(
        report_id=report_id,
        status="processing"
    )


@router.get("/status/{report_id}", response_model=ReportStatusResponse)
async def get_report_status(report_id: str):
    """Consulta el estado de generación de un reporte."""
    data = await redis_client.get(f"report:{report_id}")
    if not data:
        raise HTTPException(status_code=404, detail="Reporte no encontrado o expirado")
    
    info = json.loads(data)
    return ReportStatusResponse(
        report_id=info["id"],
        status=info["status"],
        progress=info.get("progress", 0),
        report_data=info.get("report_data"),
        download_url=f"/api/v1/reports/download/{report_id}" if info["status"] == "completed" else None,
        error_message=info.get("error"),
        renderer=info.get("renderer"),
    )


@router.get("/download/{report_id}")
async def download_report_pdf(report_id: str):
    """Descarga el PDF generado."""
    data = await redis_client.get(f"report:{report_id}")
    if not data:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")
    
    report_info = json.loads(data)
    if report_info.get("status") != "completed":
        raise HTTPException(status_code=400, detail="El reporte aún no está listo")

    pdf_path = report_info.get("pdf_path")
    if not pdf_path or not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="Archivo PDF no encontrado")

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"GeoMaps_Reporte_{report_id[:8]}.pdf"
    )


@router.get("/types")
async def get_report_types(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Lista los tipos de reporte disponibles."""
    engine = ReportEngine(db)
    return await engine.get_supported_types()


async def _generate_pdf_background(
    report_id: str,
    request: ReportRequest,
    db: AsyncSession,
    user_id: str,
):
    """Proceso asíncrono de generación de PDF."""
    try:
        # Actualizar progreso
        await _update_redis_status(report_id, {"progress": 30})

        # Generar data del reporte
        engine = ReportEngine(db)
        report_json = await engine.generate(
            user_message=request.message,
            bbox=request.bbox,
            active_layers=request.active_layers,
            user_id=user_id,
            zone_name=request.zone_name,
            zone_geometry=request.zone_geometry,
            specific_layers=request.specific_layers,
        )

        report_payload = jsonable_encoder(report_json)
        await _update_redis_status(report_id, {
            "progress": 60,
            "report_data": report_payload,
        })

        # Renderizar PDF profesional con Typst. No hay fallback HTML:
        # si Typst no esta instalado, el error debe ser visible.
        pdf_service = TypstPDFService()
        pdf_path = await pdf_service.generate_pdf(report_id, report_payload)

        # Finalizar
        await _update_redis_status(report_id, {
            "status": "completed",
            "progress": 100,
            "pdf_path": pdf_path,
            "renderer": "typst",
            "completed_at": datetime.now().isoformat()
        })

    except Exception as e:
        logger.exception(f"Error en background report generation: {e!r}")
        await _update_redis_status(report_id, {
            "status": "failed",
            "error": str(e) or repr(e)
        })

async def _update_redis_status(report_id: str, updates: Dict[str, Any]):
    """Helper para actualizar el estado en Redis."""
    data = await redis_client.get(f"report:{report_id}")
    if data:
        current = json.loads(data)
        current.update(updates)
        await redis_client.setex(f"report:{report_id}", REPORT_TTL, json.dumps(current))
