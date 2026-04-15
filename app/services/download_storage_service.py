import logging
import json
import zipfile
import tempfile
import os
import mimetypes

logger = logging.getLogger(__name__)
from uuid import UUID
from fastapi import UploadFile
from app.services.storage_service import storage_service

BUCKET = "Download"

class DownloadStorageService:

    @staticmethod
    async def upload_resource_file(
        resource_id: UUID,
        file: UploadFile,
    ) -> dict:
        """Sube el archivo al bucket Download bajo resources/{id}/"""
        content = await file.read()
        ext = file.filename.split(".")[-1].lower() if "." in file.filename else ""
        
        # Generar path estructurado
        path = f"resources/{resource_id}/{file.filename}"
        content_type = mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"

        # Usar la instancia global de supabase del storage_service
        storage_service.supabase.storage.from_(BUCKET).upload(
            path=path,
            file=content,
            file_options={"content-type": content_type},
        )

        public_url = storage_service.supabase.storage.from_(BUCKET).get_public_url(path)

        return {
            "file_url":        public_url.split("?")[0],
            "file_path":       path,
            "file_format":     ext,
            "file_size_bytes": len(content),
        }

    @staticmethod
    async def analyze_file(file: UploadFile) -> dict:
        """Extrae metadatos (features, tipo geometría) del archivo."""
        content = await file.read()
        await file.seek(0)
        ext = file.filename.split(".")[-1].lower() if "." in file.filename else ""

        if ext in ["geojson", "json"]:
            return DownloadStorageService._analyze_geojson(content)
        elif ext == "zip":
            return DownloadStorageService._analyze_zip_shapefile(content)
        elif ext == "csv":
            return DownloadStorageService._analyze_csv(content)

        return {"content_count": None, "geometry_type": None, "bbox": None}

    @staticmethod
    def _analyze_geojson(content: bytes) -> dict:
        try:
            data = json.loads(content.decode("utf-8"))
            features = data.get("features", [])
            count = len(features)
            geom_type = None
            for f in features:
                geom = f.get("geometry")
                if geom:
                    geom_type = geom.get("type")
                    break
            bbox = data.get("bbox")
            return {
                "content_count": count,
                "geometry_type": geom_type,
                "bbox":          str(bbox) if bbox else None,
            }
        except:
            return {"content_count": None, "geometry_type": None, "bbox": None}

    @staticmethod
    def _analyze_zip_shapefile(content: bytes) -> dict:
        try:
            import shapefile # Se requiere pyshp
            with tempfile.TemporaryDirectory() as tmpdir:
                zip_path = os.path.join(tmpdir, "data.zip")
                with open(zip_path, "wb") as f:
                    f.write(content)
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(tmpdir)
                shp_files = [f for f in os.listdir(tmpdir) if f.endswith(".shp")]
                if not shp_files: return {"content_count": None, "geometry_type": None, "bbox": None}
                sf = shapefile.Reader(os.path.join(tmpdir, shp_files[0]))
                return {
                    "content_count": len(sf.shapes()),
                    "geometry_type": sf.shapeTypeName,
                    "bbox":          str(sf.bbox) if sf.bbox else None,
                }
        except:
            return {"content_count": None, "geometry_type": None, "bbox": None}

    @staticmethod
    def _analyze_csv(content: bytes) -> dict:
        try:
            lines = content.decode("utf-8").strip().split("\n")
            count = max(0, len(lines) - 1)
            return {"content_count": count, "geometry_type": None, "bbox": None}
        except:
            return {"content_count": None, "geometry_type": None, "bbox": None}

    @staticmethod
    def delete_resource_files(resource_id: UUID):
        try:
            prefix = f"resources/{resource_id}/"
            # Listar y remover recursivamente
            res = storage_service.supabase.storage.from_(BUCKET).list(f"resources/{resource_id}")
            if res:
                paths = [f"{prefix}{f['name']}" for f in res]
                storage_service.supabase.storage.from_(BUCKET).remove(paths)
        except Exception as e:
            logger.error(f"[DownloadStorage] Error al eliminar: {e}")
