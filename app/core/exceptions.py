"""Excepciones personalizadas y handlers globales para GeoMaps.

Cada excepción sigue el patrón: código de error + mensaje + HTTP status.
Los handlers aseguran CORS en respuestas de error.
"""

import logging
import traceback

from fastapi import Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class MIDASException(Exception):
    """Excepción base del sistema GeoMaps."""

    def __init__(
        self,
        message: str,
        code: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: dict | None = None,
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
            status_code=status.HTTP_404_NOT_FOUND,
        )


class UnauthorizedException(MIDASException):
    def __init__(self, message: str = "No autorizado"):
        super().__init__(
            message=message,
            code="UNAUTHORIZED",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class FileUploadException(MIDASException):
    def __init__(self, message: str):
        super().__init__(
            message=message,
            code="FILE_UPLOAD_ERROR",
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class InvalidShapefileException(MIDASException):
    def __init__(self, message: str = "Shapefile inválido o corrupto"):
        super().__init__(
            message=message,
            code="INVALID_SHAPEFILE",
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class ValidationException(MIDASException):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details=details,
        )


class GeoProcessingError(MIDASException):
    def __init__(self, message: str):
        super().__init__(
            message=message,
            code="GEOPROCESSING_ERROR",
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class LLMException(MIDASException):
    def __init__(
        self, 
        message: str, 
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        code: str = "LLM_ERROR"
    ):
        super().__init__(
            message=message,
            code=code,
            status_code=status_code,
        )


class LLMRateLimitException(LLMException):
    def __init__(self, message: str = "Límite de peticiones de IA alcanzado (Rate Limit)."):
        super().__init__(
            message=message,
            code="LLM_RATE_LIMIT",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )


# ───── Handlers ─────


def _build_error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict | None = None,
) -> JSONResponse:
    """Construye una respuesta JSON de error estandarizada."""
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": {"code": code, "message": message, "details": details},
        },
    )


def _inject_cors_headers(response: JSONResponse, request: Request) -> JSONResponse:
    """Inyecta headers CORS en la respuesta de error."""
    origin = request.headers.get("origin")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


async def midas_exception_handler(request: Request, exc: MIDASException) -> JSONResponse:
    """Handler para excepciones controladas del dominio."""
    response = _build_error_response(exc.status_code, exc.code, exc.message, exc.details)
    return _inject_cors_headers(response, request)


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handler de último recurso para excepciones no controladas."""
    logger.error("EXCEPTION en %s: %s", request.url.path, exc)
    logger.error(traceback.format_exc())

    response = _build_error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "INTERNAL_SERVER_ERROR",
        f"Error interno: {exc}",
    )
    return _inject_cors_headers(response, request)


def setup_exception_handlers(app) -> None:
    """Registra los handlers de excepciones en la instancia de FastAPI."""
    app.add_exception_handler(MIDASException, midas_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)
