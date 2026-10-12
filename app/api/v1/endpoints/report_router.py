"""
GeoMaps — Router de Reportes IA.
Endpoints REST para generar, consultar y descargar reportes PDF profesionales.
"""
import logging
import os
import json
import uuid
from typing import Dict, Any
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db, SessionLocal
from app.core.utils.datetime import get_utc_now
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
from redis.exceptions import RedisError

router = APIRouter()
logger = logging.getLogger(__name__)

# Configuración de Redis para el estado de los reportes
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
REPORT_TTL = 3600  # 1 hora


@router.post("/generate", response_model=ReportGenerateResponse)
async def generate_report(
    request: ReportRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_user),
):
    """
    Genera un reporte completo.
    """
    report_id = str(uuid.uuid4())
    
    # Inicializar estado en Redis
    report_status = {
        "id": report_id,
        "user_id": str(current_user.id),
        "status": "processing",
        "progress": 10,
        "type": "custom",
        "zones": request.zone_names or ([request.zone_name] if request.zone_name else []),
        "layers": request.specific_layers or request.active_layers,
        "kpis": [],
        "progress_message": "Preparando alcance del reporte...",
        "created_at": get_utc_now().isoformat(),
    }
    try:
        await redis_client.setex(f"report:{report_id}", REPORT_TTL, json.dumps(report_status))
    except RedisError as exc:
        raise HTTPException(503, detail="El servicio de reportes no está disponible") from exc

    # Iniciar generación en segundo plano
    background_tasks.add_task(
        _generate_pdf_background,
        report_id,
        request,
        str(current_user.id),
    )

    return ReportGenerateResponse(
        report_id=report_id,
        status="processing"
    )


@router.get("/status/{report_id}", response_model=ReportStatusResponse)
async def get_report_status(report_id: uuid.UUID, current_user: User = Depends(get_current_active_user)):
    """Consulta el estado de generación de un reporte."""
    info = await _get_owned_report(report_id, current_user.id)
    return ReportStatusResponse(
        report_id=info["id"],
        status=info["status"],
        progress=info.get("progress", 0),
        report_data=info.get("report_data"),
        download_url=f"/api/v1/reports/download/{report_id}" if info["status"] == "completed" else None,
        error_message=info.get("error"),
        renderer=info.get("renderer"),
        zones=info.get("zones", []),
        layers=info.get("layers", []),
        kpis=info.get("kpis", []),
        progress_message=info.get("progress_message"),
    )


@router.get("/download/{report_id}")
async def download_report_pdf(report_id: uuid.UUID, current_user: User = Depends(get_current_active_user)):
    """Descarga el PDF generado."""
    report_info = await _get_owned_report(report_id, current_user.id)
    if report_info.get("status") != "completed":
        raise HTTPException(status_code=400, detail="El reporte aún no está listo")

    pdf_path = report_info.get("pdf_path")
    if not pdf_path or not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="Archivo PDF no encontrado")

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"GeoMaps_Reporte_{str(report_id)[:8]}.pdf"
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
    user_id: str,
):
    """El trabajo posee su sesión; no reutiliza la sesión de la petición HTTP."""
    async with SessionLocal() as db:
        await _generate_report_in_session(report_id, request, db, user_id)


async def _get_owned_report(report_id: uuid.UUID, user_id: uuid.UUID) -> Dict[str, Any]:
    try:
        data = await redis_client.get(f"report:{report_id}")
    except RedisError as exc:
        raise HTTPException(503, detail="El servicio de reportes no está disponible") from exc
    info = json.loads(data) if data else None
    if not isinstance(info, dict) or info.get("user_id") != str(user_id):
        raise HTTPException(404, detail="Reporte no encontrado o expirado")
    return info


async def _generate_report_in_session(
    report_id: str, request: ReportRequest, db: AsyncSession, user_id: str,
):
    """Proceso asíncrono de generación de PDF."""
    try:
        # Actualizar progreso
        await _update_redis_status(report_id, {
            "progress": 30,
            "progress_message": "Consultando datos espaciales...",
        })

        # Generar data del reporte
        engine = ReportEngine(db)
        report_json = await engine.generate(
            user_message=request.message,
            bbox=request.bbox,
            active_layers=request.active_layers,
            user_id=user_id,
            zone_name=request.zone_name,
            zone_names=request.zone_names,
            zone_geometry=request.zone_geometry,
            zone_geometries=request.zone_geometries,
            specific_layers=request.specific_layers,
            map_screenshot=request.map_screenshot,
            map_screenshots=jsonable_encoder(request.map_screenshots),
            comparison_mode=request.comparison_mode,
        )

        report_payload = jsonable_encoder(report_json)
        await _update_redis_status(report_id, {
            "progress": 60,
            "progress_message": "Generando PDF profesional...",
            "report_data": report_payload,
            "zones": report_payload.get("zones", []),
            "layers": report_payload.get("layers", []),
            "kpis": report_payload.get("kpis", [])[:3],
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
            "progress_message": "Reporte listo para descargar.",
            "completed_at": get_utc_now().isoformat()
        })

    except Exception as e:
        logger.exception(f"Error en background report generation: {e!r}")
        await _update_redis_status(report_id, {
            "status": "failed",
            "error": "No se pudo generar el reporte. Inténtalo de nuevo."
        })

async def _update_redis_status(report_id: str, updates: Dict[str, Any]):
    """Helper para actualizar el estado en Redis."""
    data = await redis_client.get(f"report:{report_id}")
    if data:
        current = json.loads(data)
        current.update(updates)
        await redis_client.setex(f"report:{report_id}", REPORT_TTL, json.dumps(current))
