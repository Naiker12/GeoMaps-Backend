import json
import tempfile
import uuid
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from fastapi import UploadFile

from app.services.storage import storage_service


class DownloadStorageService:
    @staticmethod
    async def analyze_file(file: UploadFile) -> dict[str, Any]:
        filename = (file.filename or "").lower()
        content = await file.read()

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

        geometry_types = {
            feature.get("geometry", {}).get("type")
            for feature in features
            if isinstance(feature, dict) and feature.get("geometry")
        }
        geometry_type = next(iter(geometry_types)) if len(geometry_types) == 1 else "Mixed"

        return {
            "file_size_bytes": len(content),
            "content_count": len(features),
            "geometry_type": geometry_type,
        }

    @staticmethod
    def _analyze_csv(content: bytes) -> dict[str, Any]:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            dataframe = pd.read_csv(tmp_path)
            return {
                "file_size_bytes": len(content),
                "content_count": int(len(dataframe)),
            }
        finally:
            tmp_path.unlink(missing_ok=True)

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
