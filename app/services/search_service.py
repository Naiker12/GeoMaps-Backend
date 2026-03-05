
import re
import json
import uuid
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select, func
from app.db.models.layer import LayerFeature, Layer
from app.db.models.project import Project, ProjectLot

class SearchService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def search(self, query: str) -> Dict[str, Any]:
        """
        Sistema de búsqueda inteligente:
        1. Detectar si es una coordenada (lat, lon).
        2. Si no, buscar por texto en nombres, códigos y propiedades JSONB.
        """
        query = query.strip()
        
        # Regex para detectar coordenadas tipo: 10.123, -74.456 o 10.123 -74.456
        coord_regex = r"^(-?\d+(\.\d+)?)\s*,\s*(-?\d+(\.\d+)?)$|^(-?\d+(\.\d+)?)\s+(-?\d+(\.\d+)?)$"
        match = re.match(coord_regex, query)
        
        if match:
            # Es una coordenada
            groups = match.groups()
            if groups[0] is not None:
                lat, lon = float(groups[0]), float(groups[2])
            else:
                lat, lon = float(groups[4]), float(groups[6])
            
            return await self._search_by_coordinates(lat, lon)
        else:
            # Es una búsqueda por texto
            return await self._search_by_text(query)

    async def _search_by_coordinates(self, lat: float, lon: float) -> Dict[str, Any]:
        """
        Busca el predio (LayerFeature) o lote (ProjectLot) más cercano a un punto.
        """
        # Consulta para LayerFeature
        # Ordenamos por distancia al punto dado
        stmt_features = text("""
            SELECT 
                lf.id, 
                lf.properties, 
                ST_AsGeoJSON(lf.geom) as geometry,
                ST_Distance(lf.geom, ST_SetSRID(ST_Point(:lon, :lat), 4326)) as distance,
                'feature' as type
            FROM layer_features lf
            ORDER BY lf.geom <-> ST_SetSRID(ST_Point(:lon, :lat), 4326)
            LIMIT 1
        """)
        
        # Consulta para ProjectLot
        stmt_lots = text("""
            SELECT 
                pl.id, 
                pl.identifier as name,
                ST_AsGeoJSON(pl.geometry) as geometry,
                ST_Distance(pl.geometry, ST_SetSRID(ST_Point(:lon, :lat), 4326)) as distance,
                'lot' as type
            FROM project_lots pl
            WHERE pl.geometry IS NOT NULL
            ORDER BY pl.geometry <-> ST_SetSRID(ST_Point(:lon, :lat), 4326)
            LIMIT 1
        """)
        
        results = []
        
        # Ejecutar búsquedas
        res_features = await self.db.execute(stmt_features, {"lat": lat, "lon": lon})
        row_feat = res_features.mappings().first()
        if row_feat:
            results.append({**row_feat, "layer_id": row_feat.get("layer_id")})
            
        res_lots = await self.db.execute(stmt_lots, {"lat": lat, "lon": lon})
        row_lot = res_lots.mappings().first()
        if row_lot:
            results.append(row_lot)
            
        # Ordenar por distancia y tomar el mejor
        if not results:
            return {"type": "FeatureCollection", "features": []}
            
        best = sorted(results, key=lambda x: x['distance'])[0]
        
        # Mapear a GeoJSON
        feature = {
            "type": "Feature",
            "geometry": json.loads(best['geometry']),
            "properties": {
                "id": str(best['id']),
                "source": best['type'],
                "search_mode": "coordinates"
            }
        }
        
        if best['type'] == 'feature':
            feature["properties"].update(best['properties'] or {})
            feature["properties"]["layer_id"] = str(best.get('layer_id'))
        else:
            feature["properties"]["name"] = best['name']
            
        return {
            "type": "FeatureCollection",
            "features": [feature]
        }

    async def _search_by_text(self, q: str) -> Dict[str, Any]:
        """
        Busca en:
        - LayerFeature.properties (JSONB)
        - Project.name
        - ProjectLot.identifier
        """
        search_term = f"%{q}%"
        
        # 1. Buscar en Layer Features (predios)
        # Buscamos en todas las propiedades del JSONB
        # PostgreSQL permite buscar en valores de JSONB de forma eficiente
        stmt_features = text("""
            SELECT 
                lf.id, 
                lf.layer_id,
                lf.properties, 
                ST_AsGeoJSON(lf.geom) as geometry,
                'feature' as type
            FROM layer_features lf
            WHERE EXISTS (
                SELECT 1 FROM jsonb_each_text(lf.properties) WHERE value ILIKE :q
            )
            LIMIT 10
        """)
        
        # 2. Buscar en Proyectos
        stmt_projects = text("""
            SELECT 
                p.id, 
                p.name,
                p.description,
                ST_AsGeoJSON(pl.geometry) as geometry,
                'project' as type
            FROM projects p
            JOIN project_locations pl ON p.id = pl.project_id
            WHERE p.name ILIKE :q OR p.description ILIKE :q
            LIMIT 10
        """)
        
        # 3. Buscar en Lotes
        stmt_lots = text("""
            SELECT 
                pl.id, 
                pl.identifier as name,
                ST_AsGeoJSON(pl.geometry) as geometry,
                'lot' as type
            FROM project_lots pl
            WHERE pl.identifier ILIKE :q
            LIMIT 10
        """)
        
        features = []
        
        # Ejecutar búsquedas
        res_feat = await self.db.execute(stmt_features, {"q": search_term})
        for row in res_feat.mappings():
            feat = {
                "type": "Feature",
                "geometry": json.loads(row['geometry']),
                "properties": {
                    "id": str(row['id']),
                    "layer_id": str(row['layer_id']),
                    "source": "feature"
                }
            }
            feat["properties"].update(row['properties'] or {})
            features.append(feat)
            
        res_proj = await self.db.execute(stmt_projects, {"q": search_term})
        for row in res_proj.mappings():
            features.append({
                "type": "Feature",
                "geometry": json.loads(row['geometry']) if row['geometry'] else None,
                "properties": {
                    "id": str(row['id']),
                    "name": row['name'],
                    "description": row['description'],
                    "source": "project"
                }
            })
            
        res_lots = await self.db.execute(stmt_lots, {"q": search_term})
        for row in res_lots.mappings():
            features.append({
                "type": "Feature",
                "geometry": json.loads(row['geometry']) if row['geometry'] else None,
                "properties": {
                    "id": str(row['id']),
                    "name": row['name'],
                    "source": "lot"
                }
            })
            
        return {
            "type": "FeatureCollection",
            "features": features[:15] # Limitar total
        }

    async def get_suggestions(self, limit: int = 5) -> List[str]:
        """
        Retorna sugerencias aleatorias basadas en lo que hay en la base de datos.
        """
        # SQL para obtener una mezcla de nombres de proyectos y nombres de capas.
        stmt = text("""
            SELECT text FROM (
                (SELECT name as text FROM projects LIMIT 15)
                UNION
                (SELECT name as text FROM layers LIMIT 15)
            ) AS sub
            ORDER BY RANDOM()
            LIMIT :limit
        """)
        
        result = await self.db.execute(stmt, {"limit": limit})
        suggestions = [row[0] for row in result.fetchall()]
        
        # Si no hay suficientes datos en la DB, rellenar con default
        defaults = ['Predios GIS', 'Crespo', 'Zonificación', 'Capas Sociales', '10.4284, -75.5141']
        while len(suggestions) < limit and defaults:
            d = defaults.pop(0)
            if d not in suggestions:
                suggestions.append(d)
                
        return suggestions[:limit]
