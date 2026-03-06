import uuid
import os
import shutil
import zipfile
import tempfile
import json
from typing import List, Dict, Any, Optional
import geopandas as gpd
from fastapi import UploadFile, HTTPException

from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.layer_repository import LayerRepository
from app.schemas.layer import LayerCreate
from app.services.storage_service import storage_service

class LayerService:
    def __init__(self, db: AsyncSession):
        self.repository = LayerRepository(db)
        self.storage = storage_service

    async def process_and_upload_layer(
        self,
        layer_in: LayerCreate,
        file: UploadFile,
        user_id: uuid.UUID
    ):
        """
        Recibe un GeoJSON o Shapefile (.zip), lo valida, convierte a WGS84, 
        persiste metadatos en layers, sube a Supabase y luego carga las features (PostGIS).
        """
        filename = file.filename.lower()
        if not (filename.endswith('.zip') or filename.endswith('.geojson')):
            raise HTTPException(status_code=400, detail="El archivo no es soportado. Use .zip para Shapefiles o .geojson.")
            
        source_type = "shapefile" if filename.endswith('.zip') else "geojson"
        
        # Subir primero a Supabase con el StorageService
        file_url = await self.storage.upload_file(file, "shapefiles")

        # Reposicionar el cursor del UploadFile al inicio para poder leerlo localmente
        await file.seek(0)
        
        # Guardaremos todo el trabajo en una carpeta temporal para procesar con GeoPandas
        with tempfile.TemporaryDirectory() as tmpdirname:
            # Escribir archivo original
            original_path = os.path.join(tmpdirname, file.filename)
            with open(original_path, "wb") as buffer:
                content = await file.read()
                buffer.write(content)
            
            # Cargar con geopandas dependiendo de tipo
            if source_type == "shapefile":
                # Validar la estructura del zip
                with zipfile.ZipFile(original_path, 'r') as zip_ref:
                    namelist = zip_ref.namelist()
                    # Mapear extensiones, shapefile necesita .shp, .shx, .dbf
                    exts = [os.path.splitext(n)[1].lower() for n in namelist]
                    
                    if not ('.shp' in exts and '.dbf' in exts and '.shx' in exts):
                        raise HTTPException(
                            status_code=400, 
                            detail="El Shapefile .zip debe contener al menos .shp, .shx, .dbf."
                        )
                    # Extraer para que geopandas pueda leer
                    zip_ref.extractall(tmpdirname)
                
                # Buscar el .shp extraído
                shp_files = [f for f in os.listdir(tmpdirname) if f.endswith('.shp')]
                if not shp_files:
                    raise HTTPException(status_code=400, detail="No se encontró un archivo .shp en la raíz del zip.")
                read_path = os.path.join(tmpdirname, shp_files[0])
            else:
                read_path = original_path

            # Leer con GeoPandas
            try:
                gdf = gpd.read_file(read_path)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"No se pudo parsear el archivo geoespacial: {str(e)}")

            if gdf.crs is None:
                raise HTTPException(status_code=400, detail="El archivo no contiene un Sistema de Referencia Espacial (CRS).")

            # Convertir siempre a WGS84 (EPSG:4326)
            if gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(epsg=4326)
            
            # Filtrar geometrías inválidas
            gdf = gdf[gdf.is_valid]

            if gdf.empty:
                raise HTTPException(status_code=400, detail="El archivo no contiene geometrías válidas.")

            geometry_type = gdf.geom_type.unique()[0]

            # Insert Metadata
            layer_created = await self.repository.create_layer(
                layer_in=layer_in,
                geometry_type=geometry_type,
                source_type=source_type,
                file_url=file_url,
                user_id=user_id
            )

            # Preparar bulk insert
            features_data = []
            for _, row in gdf.iterrows():
                # Propiedades omitiendo geom
                props = json.loads(row.drop("geometry").to_json())
                wkt = row.geometry.wkt
                features_data.append({
                    "properties": props,
                    "geom_wkt": wkt
                })
            
            # Insertar todas las geometrías en chunk
            await self.repository.insert_features_bulk(layer_id=layer_created.id, features_data=features_data)

        # Devolver el modelo
        return layer_created

    async def get_layer_geojson(self, layer_id: uuid.UUID) -> dict:
        layer = await self.repository.get_by_id(layer_id)
        if not layer:
            raise HTTPException(status_code=404, detail="La capa no existe.")
            
        return await self.repository.get_features_as_geojson(layer_id)

    async def get_features_properties(self, layer_ids: List[uuid.UUID]) -> List[dict]:
        return await self.repository.get_features_properties(layer_ids)

    async def get_feature_by_id(self, feature_id: Any) -> dict:
        feature = await self.repository.get_feature_by_id(feature_id)
        if not feature:
            raise HTTPException(status_code=404, detail="La entidad no existe.")
        return feature

    async def update_layer(self, layer_id: uuid.UUID, layer_in: Dict[str, Any]) -> Optional[Any]:
        return await self.repository.update_layer(layer_id, layer_in)

    async def list_layers(self, visibility: str = None) -> List[Any]:
        return await self.repository.get_all(visibility=visibility)

    async def delete_layer(self, layer_id: uuid.UUID):
        success = await self.repository.delete_layer(layer_id)
        if not success:
            raise HTTPException(status_code=404, detail="La capa no existe.")
        return {"success": True}
