from typing import Any, Dict, Optional
from fastapi import Request, status
from fastapi.responses import JSONResponse

class MIDASException(Exception):
    def __init__(
        self, 
        message: str, 
        code: str, 
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details
        super().__init__(message)

class ProjectNotFoundException(MIDASException):
    def __init__(self, project_id: str):
        super().__init__(
            message=f"Proyecto con ID {project_id} no encontrado",
            code="PROJECT_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND
        )

class UnauthorizedException(MIDASException):
    def __init__(self, message: str = "No autorizado"):
        super().__init__(
            message=message,
            code="UNAUTHORIZED",
            status_code=status.HTTP_401_UNAUTHORIZED
        )

class FileUploadException(MIDASException):
    def __init__(self, message: str):
        super().__init__(
            message=message,
            code="FILE_UPLOAD_ERROR",
            status_code=status.HTTP_400_BAD_REQUEST
        )

class InvalidShapefileException(MIDASException):
    def __init__(self, message: str = "Shapefile inválido o corrupto"):
        super().__init__(
            message=message,
            code="INVALID_SHAPEFILE",
            status_code=status.HTTP_400_BAD_REQUEST
        )

class ValidationException(MIDASException):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details=details
        )

async def midas_exception_handler(request: Request, exc: MIDASException):
    response = JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details
            }
        }
    )
    # Forzar CORS en la respuesta de error por si el middleware falla en excepciones
    origin = request.headers.get("origin")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response

import traceback
import logging
logger = logging.getLogger(__name__)

async def global_exception_handler(request: Request, exc: Exception):
    error_msg = str(exc)
    logger.error(f"GLOBAL EXCEPTION en {request.url.path}: {error_msg}")
    logger.error(traceback.format_exc())
    
    response = JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": f"Error interno: {error_msg}"
            }
        }
    )
    # Forzar CORS
    origin = request.headers.get("origin")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response
