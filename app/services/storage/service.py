"""Servicio de almacenamiento compatible con Supabase Storage."""

import logging
import mimetypes
import re
import unicodedata
import uuid
from dataclasses import dataclass

from fastapi import UploadFile

from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 50 * 1024 * 1024


@dataclass(frozen=True)
class StoredFileInfo:
    bucket: str
    path: str
    public_url: str
    mime_type: str
    file_size_bytes: int
    extension: str
    original_filename: str


BUCKET_MAP = {
    "layers": "Capas",
    "capas": "Capas",
    "profiles": "profiles",
    "profile": "profiles",
    "avatars": "profiles",
    "images": "Imagen",
    "image": "Imagen",
    "imagen": "Imagen",
    "models": "Imagen3d",
    "model": "Imagen3d",
    "imagen3d": "Imagen3d",
    "projects": "project",
    "project": "project",
    "projects/images": "Imagen",
    "projects/models": "Imagen3d",
    "projects/shapefiles": "project",
    "shapefile": "project",
    "resources": "resources",
    "downloads": "Download",
    "download": "Download",
}


class StorageService:
    def __init__(self):
        from supabase import Client, create_client

        if not settings.SUPABASE_SERVICE_KEY:
            logger.warning(
                "SUPABASE_SERVICE_KEY no esta configurada; Storage usara anon key. "
                "Esto puede fallar si las policies no permiten uploads desde backend."
            )

        self.supabase: Client = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_SERVICE_KEY or settings.SUPABASE_ANON_KEY,
        )

    async def upload_file(self, file: UploadFile, category: str = "layers") -> str:
        info = await self.upload_file_info(file, category)
        return info.public_url

    async def upload_file_info(self, file: UploadFile, category: str = "layers") -> StoredFileInfo:
        bucket = self._resolve_bucket(category)
        return await self.upload_file_to_bucket(file, bucket)

    async def upload_file_to_bucket(
        self,
        file: UploadFile,
        bucket: str,
        path_prefix: str | None = None,
    ) -> StoredFileInfo:
        content = await file.read()

        if len(content) > MAX_FILE_SIZE:
            raise ValueError("Archivo demasiado grande")

        content_type = mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
        safe_filename = self._sanitize_filename(file.filename or "archivo")
        filename = f"{uuid.uuid4()}-{safe_filename}"
        clean_prefix = (path_prefix or "").strip("/")
        storage_path = f"{clean_prefix}/{filename}" if clean_prefix else filename
        extension = self._file_extension(safe_filename)

        try:
            response = self.supabase.storage.from_(bucket).upload(
                path=storage_path,
                file=content,
                file_options={"content-type": content_type},
            )

            if hasattr(response, "error") and response.error:
                raise RuntimeError(response.error)

            public_url = self.supabase.storage.from_(bucket).get_public_url(storage_path)
            clean_url = public_url.split("?")[0]

            logger.info("Archivo subido correctamente - bucket: '%s', path: '%s'", bucket, storage_path)
            logger.info("URL almacenada: %s", clean_url)

            return StoredFileInfo(
                bucket=bucket,
                path=storage_path,
                public_url=clean_url,
                mime_type=content_type,
                file_size_bytes=len(content),
                extension=extension,
                original_filename=file.filename or "archivo",
            )

        except Exception as exc:
            logger.error("Error de almacenamiento: %s", exc)
            raise RuntimeError(f"Fallo en carga: {exc}") from exc

    def _resolve_bucket(self, category: str) -> str:
        normalized = (category or "layers").strip().lower()
        return BUCKET_MAP.get(normalized, "Capas")

    async def create_signed_url(self, bucket: str, file_path: str, expires_in: int = 3600) -> str:
        """Genera una URL temporal para buckets privados de Supabase Storage."""
        try:
            response = self.supabase.storage.from_(bucket).create_signed_url(file_path, expires_in)
            signed_url = response.get("signedURL") or response.get("signedUrl")

            if not signed_url:
                raise RuntimeError("Supabase no retorno una URL firmada")

            if signed_url.startswith("http"):
                return signed_url

            return f"{settings.SUPABASE_URL}{signed_url}"
        except Exception as exc:
            logger.error(
                "Error generando URL firmada - bucket: '%s', path: '%s': %s",
                bucket,
                file_path,
                exc,
            )
            raise RuntimeError(f"No se pudo generar URL firmada: {exc}") from exc

    def _sanitize_filename(self, filename: str) -> str:
        """Elimina tildes, espacios y caracteres especiales del nombre del archivo."""
        normalized = unicodedata.normalize("NFKD", filename)
        ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
        safe = re.sub(r"[^\w.\-]", "_", ascii_name)
        return safe

    def _file_extension(self, filename: str) -> str:
        if "." not in filename:
            return ""
        return f".{filename.rsplit('.', 1)[-1].lower()}"

    async def delete_file(self, file_url: str) -> bool:
        try:
            if "/storage/v1/object/public/" not in file_url:
                logger.warning("URL de storage invalida o no reconocida: %s", file_url)
                return False

            clean_url = file_url.split("?")[0]
            after_public = clean_url.split("/storage/v1/object/public/")[1]

            parts = after_public.split("/", 1)
            if len(parts) < 2:
                logger.error("No se pudo extraer ruta del archivo desde URL: %s", file_url)
                return False

            return await self.delete_file_by_path(parts[0], parts[1])

        except Exception as exc:
            logger.error("Error eliminando archivo: %s", exc, exc_info=True)
            return False

    async def delete_file_by_path(self, bucket: str, file_path: str) -> bool:
        try:
            logger.info("Eliminando archivo - bucket: '%s', path: '%s'", bucket, file_path)
            response = self.supabase.storage.from_(bucket).remove([file_path])

            if not response:
                logger.warning("Supabase no confirmo la eliminacion de: %s", file_path)
                return False

            logger.info("Archivo eliminado correctamente: %s", file_path)
            return True

        except Exception as exc:
            logger.error("Error eliminando archivo: %s", exc, exc_info=True)
            return False

    async def download_file_by_path(self, bucket: str, file_path: str) -> bytes:
        try:
            logger.info("Descargando archivo - bucket: '%s', path: '%s'", bucket, file_path)
            data = self.supabase.storage.from_(bucket).download(file_path)
            if not isinstance(data, bytes):
                raise RuntimeError("Supabase no retorno bytes para el archivo")
            return data
        except Exception as exc:
            logger.error("Error descargando archivo: %s", exc, exc_info=True)
            raise RuntimeError(f"No se pudo descargar archivo: {exc}") from exc


storage_service = StorageService()
