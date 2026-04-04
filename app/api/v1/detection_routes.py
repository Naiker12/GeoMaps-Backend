from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, status
from app.services.object_detection_service import ObjectDetectionService
from app.core.exceptions import GeoProcessingError
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Inyección de dependencia para el servicio
def get_detection_service() -> ObjectDetectionService:
    return ObjectDetectionService()

@router.post("/detect", response_model=Dict[str, Any], tags=["Object Detection"])
async def detect_objects(
    file: UploadFile = File(..., description="Imagen del mapa capturada por el frontend"),
    west: float = Form(..., description="Límite oeste del mapa"),
    south: float = Form(..., description="Límite sur del mapa"),
    east: float = Form(..., description="Límite este del mapa"),
    north: float = Form(..., description="Límite norte del mapa"),
    confidence: float = Form(0.25, description="Umbral de confianza para filtrar detecciones"),
    detection_service: ObjectDetectionService = Depends(get_detection_service)
):
    """
    Endpoint principal para la detección de objetos georreferenciados.
    
    Toma una imagen (PNG/JPG) y sus límites geográficos para realizar la inferencia YOLOv8 
    y retornar un GeoJSON con los polígonos de las cajas delimitadoras.
    """
    
    # 1. Validar que el archivo sea una imagen
    if file.content_type not in ["image/png", "image/jpeg", "image/jpg"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Formato de archivo no soportado: {file.content_type}. Solo se aceptan imágenes PNG o JPEG."
        )

    # 2. Leer contenido de la imagen
    try:
        image_bytes = await file.read()
    except Exception as e:
        logger.error(f"Error leyendo archivo de imagen: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error crítico al procesar el archivo de imagen"
        )

    # 3. Preparar los límites geográficos
    bounds = {
        "west": west,
        "south": south,
        "east": east,
        "north": north
    }

    # 4. Ejecutar el servicio de detección
    try:
        logger.info(f"Iniciando detección con confianza: {confidence}")
        result = await detection_service.detect_in_map_view(
            image_bytes=image_bytes,
            bounds=bounds,
            confidence_threshold=confidence
        )
        return result
        
    except GeoProcessingError as e:
        logger.error(f"Error de procesamiento geoespacial: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )
    except Exception as e:
        logger.exception(f"Error inesperado en el endpoint de detección: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del motor de detección"
        )
