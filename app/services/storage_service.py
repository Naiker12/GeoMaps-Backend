"""Servicio de almacenamiento compatible con S3/Supabase Storage."""

import logging
import uuid
import mimetypes
import unicodedata
import re
from fastapi import UploadFile
from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 50 * 1024 * 1024

BUCKET_MAP = {
    "layers": "Capas",
    "images": "Imagen",
    "models": "Imagen3d",
    "resources": "resources"
}


class StorageService:
    def __init__(self):
        from supabase import create_client, Client
        self.supabase: Client = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_ANON_KEY
        )

    async def upload_file(self, file: UploadFile, category: str = "layers") -> str:
        content = await file.read()

        if len(content) > MAX_FILE_SIZE:
            raise ValueError("Archivo demasiado grande")

        bucket = self._resolve_bucket(category)
        content_type = mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"

        safe_filename = self._sanitize_filename(file.filename or "archivo")
        filename = f"{uuid.uuid4()}-{safe_filename}"

        try:
            response = self.supabase.storage.from_(bucket).upload(
                path=filename,
                file=content,
                file_options={"content-type": content_type}
            )

            if hasattr(response, "error") and response.error:
                raise Exception(response.error)

            public_url = self.supabase.storage.from_(bucket).get_public_url(filename)

            clean_url = public_url.split("?")[0]

            logger.info(f"Archivo subido correctamente — bucket: '{bucket}', path: '{filename}'")
            logger.info(f"URL almacenada: {clean_url}")

            return clean_url

        except Exception as exc:
            logger.error(f"Error de almacenamiento: {exc}")
            raise RuntimeError(f"Fallo en carga: {exc}")

    def _resolve_bucket(self, category: str) -> str:
        return BUCKET_MAP.get(category, "Capas")

    def _sanitize_filename(self, filename: str) -> str:
        """Elimina tildes, espacios y caracteres especiales del nombre del archivo.
        Supabase Storage rechaza cualquier caracter fuera de letras ASCII, números, guiones y puntos."""

        normalized = unicodedata.normalize("NFKD", filename)
        ascii_name = normalized.encode("ascii", "ignore").decode("ascii")

        # Reemplazar espacios y cualquier caracter no permitido por guión bajo
        safe = re.sub(r"[^\w.\-]", "_", ascii_name)

        return safe

    async def delete_file(self, file_url: str) -> bool:
        try:
            if "/storage/v1/object/public/" not in file_url:
                logger.warning(f"URL de storage inválida o no reconocida: {file_url}")
                return False

            clean_url = file_url.split("?")[0]

            after_public = clean_url.split("/storage/v1/object/public/")[1]

            parts = after_public.split("/", 1)
            if len(parts) < 2:
                logger.error(f"No se pudo extraer ruta del archivo desde URL: {file_url}")
                return False

            bucket = parts[0]
            file_path = parts[1]

            logger.info(f"Eliminando archivo — bucket: '{bucket}', path: '{file_path}'")

            response = self.supabase.storage.from_(bucket).remove([file_path])

            if not response:
                logger.warning(f"Supabase no confirmó la eliminación de: {file_path}")
                return False

            logger.info(f"Archivo eliminado correctamente: {file_path}")
            return True

        except Exception as exc:
            logger.error(f"Error eliminando archivo: {exc}", exc_info=True)
            return False


storage_service = StorageService()