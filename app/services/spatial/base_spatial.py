"""
GeoMaps — Base para Analizadores Espaciales.
Clase base con helpers PostGIS compartidos por todos los analyzers.
"""
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class BaseSpatialAnalyzer:
    """
    Clase base para analizadores espaciales.
    Provee helpers comunes para queries PostGIS y estadísticas.
    """

    def __init__(self, db: AsyncSession, bbox: Optional[Dict[str, float]] = None, layers: Optional[List[str]] = None):
        self.db = db
        self.bbox = bbox
        self.layers = layers or []

    def _layer_filter_clause(self, alias: str = "l") -> tuple[str, Dict[str, Any]]:
        """Limita consultas agregadas a las capas resueltas para el reporte."""
        if not self.layers:
            return "", {}
        placeholders = []
        params: Dict[str, Any] = {}
        for index, layer_name in enumerate(self.layers):
            key = f"layer_name_{index}"
            placeholders.append(f":{key}")
            params[key] = layer_name
        return f" AND {alias}.name IN ({', '.join(placeholders)})", params

    async def query_features_in_bbox(
        self,
        layer_name: str,
        limit: int = 500,
        fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Consulta features de una capa dentro del bbox actual."""
        try:
            # Obtener layer_id
            layer_q = await self.db.execute(
                text("SELECT id FROM layers WHERE name = :name LIMIT 1"),
                {"name": layer_name}
            )
            layer_row = layer_q.scalar()
            if not layer_row:
                logger.warning(f"Capa '{layer_name}' no encontrada")
                return []

            # Construir query con o sin bbox
            if self.bbox and all(k in self.bbox for k in ("xmin", "ymin", "xmax", "ymax")):
                query = text("""
                    SELECT properties, ST_AsGeoJSON(geom) as geojson
                    FROM layer_features
                    WHERE layer_id = :lid
                      AND ST_Intersects(
                        geom,
                        ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326)
                      )
                    LIMIT :lim
                """)
                params = {
                    "lid": layer_row,
                    "xmin": self.bbox["xmin"],
                    "ymin": self.bbox["ymin"],
                    "xmax": self.bbox["xmax"],
                    "ymax": self.bbox["ymax"],
                    "lim": limit,
                }
            else:
                query = text("""
                    SELECT properties, ST_AsGeoJSON(geom) as geojson
                    FROM layer_features
                    WHERE layer_id = :lid
                    LIMIT :lim
                """)
                params = {"lid": layer_row, "lim": limit}

            result = await self.db.execute(query, params)
            rows = result.fetchall()

            features = []
            for row in rows:
                props = row[0] if isinstance(row[0], dict) else {}
                if fields:
                    props = {k: v for k, v in props.items() if k in fields}
                features.append(props)

            return features

        except Exception as e:
            logger.error(f"Error en query_features_in_bbox: {e}")
            await self.db.rollback()
            return []

    async def count_features_in_bbox(self, layer_name: str) -> int:
        """Cuenta features de una capa dentro del bbox."""
        try:
            layer_q = await self.db.execute(
                text("SELECT id FROM layers WHERE name = :name LIMIT 1"),
                {"name": layer_name}
            )
            layer_row = layer_q.scalar()
            if not layer_row:
                return 0

            if self.bbox and all(k in self.bbox for k in ("xmin", "ymin", "xmax", "ymax")):
                query = text("""
                    SELECT COUNT(*) FROM layer_features
                    WHERE layer_id = :lid
                      AND ST_Intersects(
                        geom,
                        ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326)
                      )
                """)
                params = {
                    "lid": layer_row,
                    "xmin": self.bbox["xmin"],
                    "ymin": self.bbox["ymin"],
                    "xmax": self.bbox["xmax"],
                    "ymax": self.bbox["ymax"],
                }
            else:
                query = text("SELECT COUNT(*) FROM layer_features WHERE layer_id = :lid")
                params = {"lid": layer_row}

            result = await self.db.execute(query, params)
            return result.scalar() or 0

        except Exception as e:
            logger.error(f"Error en count_features_in_bbox: {e}")
            await self.db.rollback()
            return 0

    async def get_field_distribution(
        self,
        layer_name: str,
        field: str,
        limit: int = 15
    ) -> List[Dict[str, Any]]:
        """Calcula distribución de valores de un campo (GROUP BY + COUNT)."""
        try:
            layer_q = await self.db.execute(
                text("SELECT id FROM layers WHERE name = :name LIMIT 1"),
                {"name": layer_name}
            )
            layer_row = layer_q.scalar()
            if not layer_row:
                return []

            bbox_clause = ""
            params: Dict[str, Any] = {"lid": layer_row, "lim": limit}

            if self.bbox and all(k in self.bbox for k in ("xmin", "ymin", "xmax", "ymax")):
                bbox_clause = """
                    AND ST_Intersects(
                        geom,
                        ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326)
                    )
                """
                params.update(self.bbox)

            query = text(f"""
                SELECT
                    COALESCE(properties->>'{field}', 'Sin Especificar') as category,
                    COUNT(*) as count
                FROM layer_features
                WHERE layer_id = :lid
                {bbox_clause}
                GROUP BY category
                ORDER BY count DESC
                LIMIT :lim
            """)

            result = await self.db.execute(query, params)
            rows = result.fetchall()

            return [
                {"name": str(row[0]), "value": int(row[1])}
                for row in rows
            ]

        except Exception as e:
            logger.error(f"Error en get_field_distribution: {e}")
            await self.db.rollback()
            return []

    async def get_numeric_stats(
        self,
        layer_name: str,
        field: str
    ) -> Dict[str, Any]:
        """Calcula estadísticas numéricas (AVG, MIN, MAX, SUM) de un campo."""
        try:
            layer_q = await self.db.execute(
                text("SELECT id FROM layers WHERE name = :name LIMIT 1"),
                {"name": layer_name}
            )
            layer_row = layer_q.scalar()
            if not layer_row:
                return {}

            bbox_clause = ""
            params: Dict[str, Any] = {"lid": layer_row}

            if self.bbox and all(k in self.bbox for k in ("xmin", "ymin", "xmax", "ymax")):
                bbox_clause = """
                    AND ST_Intersects(
                        geom,
                        ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326)
                    )
                """
                params.update(self.bbox)

            query = text(f"""
                SELECT
                    COUNT(*) as total,
                    ROUND(AVG((properties->>'{field}')::numeric), 2) as avg_val,
                    MIN((properties->>'{field}')::numeric) as min_val,
                    MAX((properties->>'{field}')::numeric) as max_val,
                    ROUND(SUM((properties->>'{field}')::numeric), 2) as sum_val
                FROM layer_features
                WHERE layer_id = :lid
                  AND properties->>'{field}' IS NOT NULL
                  AND properties->>'{field}' ~ '^[0-9]'
                {bbox_clause}
            """)

            result = await self.db.execute(query, params)
            row = result.fetchone()

            if not row:
                return {}

            return {
                "total": int(row[0]),
                "average": float(row[1]) if row[1] else 0,
                "minimum": float(row[2]) if row[2] else 0,
                "maximum": float(row[3]) if row[3] else 0,
                "sum": float(row[4]) if row[4] else 0,
            }

        except Exception as e:
            logger.error(f"Error en get_numeric_stats: {e}")
            await self.db.rollback()
            return {}

    async def get_available_layers_in_bbox(self) -> List[Dict[str, Any]]:
        """Lista las capas que tienen features dentro del bbox."""
        try:
            if self.bbox and all(k in self.bbox for k in ("xmin", "ymin", "xmax", "ymax")):
                layer_filter, layer_params = self._layer_filter_clause("l")
                query = text("""
                    SELECT l.name, COUNT(lf.id) as feature_count
                    FROM layers l
                    JOIN layer_features lf ON l.id = lf.layer_id
                    WHERE l.visibility != 'PRIVATE'
                      """ + layer_filter + """
                      AND ST_Intersects(
                        lf.geom,
                        ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326)
                      )
                    GROUP BY l.name
                    ORDER BY feature_count DESC
                """)
                params = {**self.bbox, **layer_params}
            else:
                layer_filter, layer_params = self._layer_filter_clause("l")
                query = text("""
                    SELECT l.name, COUNT(lf.id) as feature_count
                    FROM layers l
                    JOIN layer_features lf ON l.id = lf.layer_id
                    WHERE l.visibility != 'PRIVATE'
                    """ + layer_filter + """
                    GROUP BY l.name
                    ORDER BY feature_count DESC
                """)
                params = layer_params

            result = await self.db.execute(query, params)
            return [
                {"name": str(row[0]), "count": int(row[1])}
                for row in result.fetchall()
            ]

        except Exception as e:
            logger.error(f"Error en get_available_layers_in_bbox: {e}")
            await self.db.rollback()
            return []
