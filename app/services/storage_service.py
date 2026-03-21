"""Servicio de almacenamiento compatible con S3/Supabase Storage.
Centraliza la lógica de carga, validación y resolución de buckets multimedia.
"""

import logging
import uuid
import mimetypes
from typing import Any
from fastapi import UploadFile
from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 50 * 1024 * 1024
BUCKET_MAP = {
    "images": "projects/images",
    "models": "projects/models",
    "layers": "layers/files",
    "resources": "resources/downloads"
}


class StorageService:
    """Implementa gestión de archivos en la nube."""

    def __init__(self):
        from supabase import create_client, Client
        self.supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)

    async def upload_file(self, file: UploadFile, category: str = "images") -> str:
        """Valida, procesa y sube un archivo enviando una URL pública de retorno."""
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise ValueError(f"Archivo excedido: {len(content) / (1024*1024):.2f}MB (Máx 50MB)")
        
        bucket = self._resolve_bucket(category)
        filename = f"{uuid.uuid4()}-{file.filename}"
        content_type = mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"

        try:
            self.supabase.storage.from_(bucket).upload(
                path=filename,
                file=content,
                file_options={"content-type": content_type}
            )
            
            return self.supabase.storage.from_(bucket).get_public_url(filename)
        except Exception as exc:
            logger.error(f"Error de almacenamiento: {exc}")
            raise RuntimeError(f"Fallo en carga: {exc}") from exc

    def _resolve_bucket(self, category: str) -> str:
        """Helper privado para mapear categorías a buckets físicos."""
        return BUCKET_MAP.get(category, "general")

    async def delete_file(self, file_url: str):
        """Intenta eliminar un archivo mediante el análisis de su URL pública."""
        try:
            filename = file_url.split("/")[-1]
            bucket = file_url.split("/storage/v1/object/public/")[-1].split("/")[0]
            self.supabase.storage.from_(bucket).remove(filename)
        except Exception as exc:
            logger.warning(f"Fallo borrado silencial: {exc}")


storage_service = StorageService()
