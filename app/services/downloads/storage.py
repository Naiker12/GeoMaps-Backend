import json
import logging
import tempfile
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool

from app.services.storage import MAX_FILE_SIZE, FileTooLargeError, storage_service

logger = logging.getLogger(__name__)


class DownloadStorageService:
    @staticmethod
    async def analyze_file(file: UploadFile) -> dict[str, Any]:
        """Analiza contenido acotado y deja el archivo listo para su carga."""
        filename = (file.filename or "").lower()
        try:
            content = await file.read(MAX_FILE_SIZE + 1)
            if len(content) > MAX_FILE_SIZE:
                raise FileTooLargeError("Archivo demasiado grande")
            return await run_in_threadpool(
                DownloadStorageService._analyze_content, filename, content
            )
        finally:
            await file.seek(0)

    @staticmethod
    def _analyze_content(filename: str, content: bytes) -> dict[str, Any]:
        if not content:
            return {"file_size_bytes": 0}

        try:
            if filename.endswith((".geojson", ".json")):
                return DownloadStorageService._analyze_geojson(content)

            if filename.endswith(".csv"):
                return DownloadStorageService._analyze_csv(content)

            if filename.endswith(".zip"):
                return DownloadStorageService._analyze_vector_zip(content)
        except Exception:
            # Los metadatos son opcionales; conservar la carga si el lector falla.
            logger.warning("No se pudieron analizar los metadatos de %s", filename, exc_info=True)
            return {"file_size_bytes": len(content)}

        return {"file_size_bytes": len(content)}

    @staticmethod
    async def upload_resource_file(resource_id: uuid.UUID, file: UploadFile) -> dict[str, Any]:
        info = await storage_service.upload_file_to_bucket(
            file=file,
            bucket="Download",
            path_prefix=f"resources/{resource_id}",
        )
        return {
            "file_url": info.public_url,
            "file_path": info.path,
            "file_format": info.extension.lstrip("."),
            "file_size_bytes": info.file_size_bytes,
        }

    @staticmethod
    async def delete_resource_files(resource_id: uuid.UUID, file_path: str | None = None) -> bool:
        if file_path:
            return await storage_service.delete_file_by_path("Download", file_path)
        return False

    @staticmethod
    def _analyze_geojson(content: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(content.decode("utf-8"))
        except UnicodeDecodeError:
            payload = json.loads(content.decode("latin-1"))

        features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(features, list):
            return {"file_size_bytes": len(content)}

        geometry_types = set()
        for feature in features:
            geometry = feature.get("geometry") if isinstance(feature, dict) else None
            if isinstance(geometry, dict) and isinstance(geometry.get("type"), str):
                geometry_types.add(geometry["type"])
        geometry_type = next(iter(geometry_types)) if len(geometry_types) == 1 else "Mixed"

        return {
            "file_size_bytes": len(content),
            "content_count": len(features),
            "geometry_type": geometry_type,
        }

    @staticmethod
    def _analyze_csv(content: bytes) -> dict[str, Any]:
        with pd.read_csv(BytesIO(content), chunksize=10_000) as chunks:
            return {
                "file_size_bytes": len(content),
                "content_count": sum(len(chunk) for chunk in chunks),
            }

    @staticmethod
    def _analyze_vector_zip(content: bytes) -> dict[str, Any]:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            dataframe = gpd.read_file(f"zip://{tmp_path}")
            geometry_types = set(dataframe.geometry.geom_type.dropna().unique())
            geometry_type = next(iter(geometry_types)) if len(geometry_types) == 1 else "Mixed"
            bounds = dataframe.total_bounds.tolist() if not dataframe.empty else None
            return {
                "file_size_bytes": len(content),
                "content_count": int(len(dataframe)),
                "geometry_type": geometry_type,
                "bbox": ",".join(str(value) for value in bounds) if bounds else None,
            }
        finally:
            tmp_path.unlink(missing_ok=True)
