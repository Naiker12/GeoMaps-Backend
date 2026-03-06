import uuid
import json
from typing import List, Optional, Any
from fastapi import UploadFile

from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.download_repository import DownloadRepository
from app.schemas.download import DownloadResourceCreate, DownloadResourceUpdate
from app.services.storage_service import storage_service
from sqlalchemy import select, func
from app.db.models.layer import Layer, LayerFeature

class DownloadService:
    def __init__(self, db: AsyncSession):
        self.repository = DownloadRepository(db)
        self.storage = storage_service

    async def get_downloads(self, show_in_public: Optional[bool] = None) -> List[Any]:
        return await self.repository.get_all(show_in_public=show_in_public)

    async def get_download_by_id(self, download_id: uuid.UUID) -> Optional[Any]:
        return await self.repository.get_by_id(download_id)

    async def create_download(
        self,
        download_in: DownloadResourceCreate,
        user_id: uuid.UUID,
        files: List[UploadFile] = []
    ):
        file_url = None
        
        # Asegurar que metadata_ siempre exista como diccionario
        if not download_in.metadata_:
            download_in.metadata_ = {}

        # ─── CASO 1: Archivo estático subido ───
        if files and len(files) > 0:
            file = files[0]
            
            # Leer archivo completo en memoria para análisis
            content = await file.read()
            total_bytes = len(content)
            
            # Calcular peso real del archivo
            if total_bytes < 1024 * 1024:
                calculated_size = f"{(total_bytes / 1024):.1f} KB"
            else:
                calculated_size = f"{(total_bytes / (1024 * 1024)):.2f} MB"
                
            calculated_elements = "1 Archivo"
            calculated_format = "Archivo"
                
            # Algoritmo de detección de contenido por extensión
            try:
                filename = file.filename.lower() if file.filename else ""
                
                if filename.endswith('.geojson') or filename.endswith('.json'):
                    calculated_format = "GeoJSON"
                    text_content = content.decode('utf-8')
                    json_data = json.loads(text_content)
                    if "features" in json_data and isinstance(json_data["features"], list):
                        calculated_elements = f"{len(json_data['features'])} registros"
                    else:
                        calculated_elements = "Sin registros"
                        
                elif filename.endswith('.zip') or filename.endswith('.shp'):
                    calculated_format = "Shapefile"
                    import geopandas as gpd
                    import tempfile
                    import os
                    import zipfile
                    
                    with tempfile.TemporaryDirectory() as tmpdirname:
                        temp_file_path = os.path.join(tmpdirname, filename)
                        with open(temp_file_path, "wb") as tmp_f:
                            tmp_f.write(content)
                            
                        try:
                            if filename.endswith('.zip'):
                                with zipfile.ZipFile(temp_file_path, 'r') as zip_ref:
                                    zip_ref.extractall(tmpdirname)
                                    namelist = zip_ref.namelist()
                                    shp_file = next((n for n in namelist if n.endswith('.shp')), None)
                                    if shp_file:
                                        gdf = gpd.read_file(os.path.join(tmpdirname, shp_file))
                                        calculated_elements = f"{len(gdf)} registros"
                                    else:
                                        calculated_elements = "1 Shapefile"
                            else:
                                gdf = gpd.read_file(temp_file_path)
                                calculated_elements = f"{len(gdf)} registros"
                        except Exception as e_geopandas:
                            print(f"[DOWNLOAD] No se pudo extraer conteo del shapefile: {e_geopandas}")
                            calculated_elements = "1 Shapefile"
                            
                elif filename.endswith('.pdf'):
                    calculated_format = "PDF"
                    calculated_elements = "1 Documento PDF"
                    
                elif filename.endswith('.csv'):
                    calculated_format = "CSV"
                    text_content = content.decode('utf-8')
                    lines = len(text_content.split('\n'))
                    calculated_elements = f"{max(0, lines - 1)} registros"
                    
            except Exception as e:
                print(f"[DOWNLOAD] Error procesando heurística de archivo: {e}")
            
            download_in.metadata_["size"] = calculated_size
            download_in.metadata_["elements"] = calculated_elements
            download_in.metadata_["format"] = calculated_format

            # Rewind el puntero para que storage_service pueda subir a Supabase
            await file.seek(0)
            file_url = await self.storage.upload_file(file, "downloads")
            
        # ─── CASO 2: Vinculado a una capa GIS existente (sin archivo) ───
        elif download_in.layer_id:
            try:
                print(f"[DOWNLOAD] Consultando capa layer_id={download_in.layer_id}")
                
                # 1. Obtener info de la capa (source_type, file_url, name)
                layer_stmt = select(Layer).where(Layer.id == download_in.layer_id)
                layer_result = await self.repository.db.execute(layer_stmt)
                layer = layer_result.scalars().first()
                
                # 2. Contar features reales en la tabla layer_features
                count_stmt = select(func.count(LayerFeature.id)).where(
                    LayerFeature.layer_id == download_in.layer_id
                )
                count_result = await self.repository.db.execute(count_stmt)
                count = count_result.scalar() or 0
                
                download_in.metadata_["elements"] = f"{count} registros"
                
                if layer:
                    # 3. Formato basado en source_type real de la capa
                    src = (layer.source_type or "").lower()
                    if src == "geojson":
                        download_in.metadata_["format"] = "GeoJSON"
                    elif src == "shapefile":
                        download_in.metadata_["format"] = "Shapefile"
                    else:
                        download_in.metadata_["format"] = "GeoJSON"
                    
                    # 4. Estimar tamaño descargando el archivo desde Supabase
                    if layer.file_url:
                        try:
                            import urllib.request
                            req = urllib.request.Request(layer.file_url, method='HEAD')
                            response = urllib.request.urlopen(req, timeout=5)
                            content_length = response.headers.get('Content-Length')
                            if content_length:
                                total_bytes = int(content_length)
                                if total_bytes < 1024 * 1024:
                                    download_in.metadata_["size"] = f"{(total_bytes / 1024):.1f} KB"
                                else:
                                    download_in.metadata_["size"] = f"{(total_bytes / (1024 * 1024)):.2f} MB"
                            else:
                                download_in.metadata_["size"] = "Capa GIS"
                        except Exception as e_size:
                            print(f"[DOWNLOAD] No se pudo obtener tamaño del archivo: {e_size}")
                            download_in.metadata_["size"] = "Capa GIS"
                    else:
                        download_in.metadata_["size"] = "Capa GIS"
                else:
                    download_in.metadata_["format"] = "GeoJSON"
                    download_in.metadata_["size"] = "Capa GIS"
                
                print(f"[DOWNLOAD] Resultado: {count} registros, formato={download_in.metadata_['format']}, size={download_in.metadata_['size']}")
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"[DOWNLOAD] Error procesando conteo de capa: {e}")
                download_in.metadata_["elements"] = "Sin datos"
                download_in.metadata_["size"] = "N/A"
                download_in.metadata_["format"] = "Desconocido"

        # ─── CASO 3: Ni archivo ni capa → valores por defecto ───
        else:
            if download_in.metadata_.get("elements") in (None, "Calculando...", "Auto-calculado"):
                download_in.metadata_["elements"] = "Sin datos"
            if download_in.metadata_.get("size") in (None, "Calculando...", "Desconocido"):
                download_in.metadata_["size"] = "N/A"
            if not download_in.metadata_.get("format"):
                download_in.metadata_["format"] = "Manual"

        return await self.repository.create_download(
            download_in=download_in,
            file_url=file_url,
            user_id=user_id
        )

    async def update_download(self, download_id: uuid.UUID, download_in: DownloadResourceUpdate) -> Optional[Any]:
        # Filtrar valores None
        update_data = {k: v for k, v in download_in.model_dump(exclude_unset=True).items() if v is not None}
        if not update_data:
            return await self.repository.get_by_id(download_id)
            
        return await self.repository.update_download(download_id, update_data)

    async def delete_download(self, download_id: uuid.UUID) -> bool:
        # Podríamos intentar borrar el archivo de Supabase Storage también si tuviéramos file_url
        download = await self.repository.get_by_id(download_id)
        if download and download.file_url:
            # self.storage.delete_file(download.file_url) (si existiera)
            pass
        return await self.repository.delete_download(download_id)
