import os
import time
import tempfile
import zipfile
import geopandas as gpd
import shapely
from app.core.exceptions import InvalidShapefileException
from app.core.logging import logger

class GeoService:
    @staticmethod
    def _safe_union(geometries):
        """
        Realiza una unión de geometrías de forma segura, evitando errores de
        tipos incompatibles en Shapely 2.x.
        """
        import shapely
        from shapely.validation import make_valid
        from shapely.ops import unary_union
        
        # 1. Asegurar que trabajamos con una lista de geometrías de Shapely
        if hasattr(geometries, "tolist"):
            geoms_list = geometries.tolist()
        else:
            geoms_list = list(geometries)
            
        # 2. Limpieza exhaustiva
        clean_geoms = []
        for g in geoms_list:
            if g is None: continue
            
            # Si no es un objeto de Shapely (podría ser un WKBElement o similar si viene de DB)
            if not hasattr(g, "geom_type"): 
                continue
                
            if g.is_empty: continue
            
            try:
                # Validar y corregir
                if not g.is_valid:
                    g = make_valid(g)
                # Forzar a 2D para evitar inconsistencias en la unión
                if shapely.has_z(g):
                    from shapely.ops import transform
                    g = transform(lambda x, y, z=None: (x, y), g)
                
                clean_geoms.append(g)
            except Exception as e:
                logger.warning(f"Geometría omitida por error técnico: {e}")
                continue
                
        if not clean_geoms:
            return None
            
        try:
            # Intentar el método más moderno de Shapely 2.x
            return shapely.union_all(clean_geoms)
        except Exception as e:
            logger.warning(f"Falla union_all, intentando unary_union clásico: {e}")
            try:
                # Fallback al método clásico de ops
                return unary_union(clean_geoms)
            except Exception as e2:
                logger.error(f"Falla total de algoritmos de unión: {e2}")
                # En última instancia, devolvemos la geometría más grande para no perder todo el dato
                return sorted(clean_geoms, key=lambda g: g.area, reverse=True)[0]

    @staticmethod
    async def process_shapefile(files: list[tuple[str, bytes]]):
        """
        Procesa archivos de shapefile con validación robusta de CRS y seguridad.
        """
        start_time = time.time()
        logger.info(f"Geomaps Processing: Iniciando validación de {len(files)} archivos.")
        
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                # 1. Validación y Extracción Segura
                for filename, content in files:
                    clean_filename = os.path.basename(filename)
                    if not clean_filename: continue
                    
                    file_path = os.path.join(tmpdir, clean_filename)
                    with open(file_path, "wb") as f:
                        f.write(content)
                    
                    if clean_filename.lower().endswith(".zip"):
                        try:
                            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                                for zip_info in zip_ref.infolist():
                                    if zip_info.filename.startswith('/') or '..' in zip_info.filename:
                                        raise InvalidShapefileException(f"Archivo malicioso detectado en ZIP: {zip_info.filename}")
                                zip_ref.extractall(tmpdir)
                        except Exception as ze:
                            if isinstance(ze, InvalidShapefileException): raise
                            raise InvalidShapefileException(f"El archivo ZIP está corrupto: {str(ze)}")

                # 2. Búsqueda profunda de archivos .shp
                shp_files = []
                for root, _, filenames in os.walk(tmpdir):
                    for f in filenames:
                        if f.lower().endswith(".shp"):
                            shp_files.append(os.path.join(root, f))

                if not shp_files:
                    raise InvalidShapefileException("No se encontró ningún archivo .shp.")
                
                shp_path = shp_files[0]
                base_path = os.path.splitext(shp_path)[0]

                # 3. Validación de integridad
                if not os.path.exists(base_path + ".shx") or not os.path.exists(base_path + ".dbf"):
                    raise InvalidShapefileException("Faltan archivos obligatorios (.shx o .dbf).")

                # 4. Lectura con GeoPandas
                try:
                    gdf = gpd.read_file(shp_path)
                except Exception as e:
                    raise InvalidShapefileException(f"Error leyendo el mapa: {str(e)}")

                if gdf is None or gdf.empty:
                    raise InvalidShapefileException("El mapa no contiene geometrías.")

                # 5. Unión de geometrías (Multilote -> Polígono único)
                unified_geom = GeoService._safe_union(gdf.geometry)

                if unified_geom is None or unified_geom.is_empty:
                    raise InvalidShapefileException("No se pudo procesar la geometría del mapa.")

                # 6. Manejo Proactivo de CRS
                prj_path = base_path + ".prj"
                prj_exists = os.path.exists(prj_path)
                
                centroid = unified_geom.centroid
                status = "SUCCESS"
                total_area = 0.0
                warning = None

                # Caso A: Sin protección de proyección (PRJ faltante)
                if not prj_exists or gdf.crs is None:
                    status = "CRS_MISSING"
                    warning = "Falta archivo .prj. El mapa puede no estar ubicado correctamente."
                    c_lat, c_lon = centroid.y, centroid.x
                    # Control de anomalías para coordenadas en metros sin PRJ
                    if abs(c_lat) > 180 or abs(c_lon) > 180:
                        logger.warning(f"Coordenadas fuera de rango WGS84 detectadas sin PRJ: ({c_lat}, {c_lon})")
                        c_lat, c_lon = 0.0, 0.0 # Evitar overflow en base de datos
                else:
                    # Caso B: Con CRS, normalizamos y calculamos área
                    try:
                        # Reproyectar a WGS84 para visualización
                        if gdf.crs.to_epsg() != 4326:
                            gdf_wgs84 = gdf.to_crs(epsg=4326)
                            unified_geom = GeoService._safe_union(gdf_wgs84.geometry)
                            centroid = unified_geom.centroid
                        
                        c_lat, c_lon = centroid.y, centroid.x
                        
                        # Cálculo de área preciso
                        try:
                            utm_crs = gdf.estimate_utm_crs()
                            gdf_m = gdf.to_crs(utm_crs)
                            temp_geom = GeoService._safe_union(gdf_m.geometry)
                            total_area = float(temp_geom.area) if temp_geom else 0.0
                        except:
                            total_area = 0.0
                            
                    except Exception as re:
                        logger.error(f"Error en reproyección: {re}")
                        c_lat, c_lon = centroid.y, centroid.x
                        status = "PROJECTION_ERROR"

                # 6. Extracción de Lotes Individuales (Fuera del else para que funcione siempre)
                lots_list = []
                gdf_lots_metric = None
                try:
                    utm_crs = gdf.estimate_utm_crs()
                    gdf_lots_metric = gdf.to_crs(utm_crs)
                except:
                    pass

                # Asegurar que trabajamos con WGS84 para los WKTs finales del inventario
                gdf_wgs84_all = gdf.to_crs(epsg=4326) if gdf.crs and gdf.crs.to_epsg() != 4326 else gdf

                for idx, row in gdf_wgs84_all.iterrows():
                    geom = row.geometry
                    if geom is None or geom.is_empty: continue
                    
                    # Identificador: LT-X por defecto o columna común
                    identifier = f"LT-{idx + 1}"
                    potential_id_cols = ['LOTE', 'ID', 'IDENTIFIER', 'REF', 'NOMBRE', 'NAME']
                    for col in potential_id_cols:
                        if col in gdf.columns and row[col] and str(row[col]).strip():
                            identifier = str(row[col]).strip()
                            break
                    
                    # Área individual
                    lot_area = 0.0
                    if gdf_lots_metric is not None:
                        try: lot_area = float(gdf_lots_metric.iloc[idx].geometry.area)
                        except: pass
                    
                    lots_list.append({
                        "identifier": identifier,
                        "geometry_wkt": geom.wkt,
                        "area_m2": lot_area,
                        "status": "Disponible"
                    })

                return {
                    "status": status,
                    "geometry_wkt": unified_geom.wkt,
                    "centroid_lat": float(c_lat),
                    "centroid_lon": float(c_lon),
                    "total_area": total_area,
                    "lots": lots_list,
                    "warning": warning
                }

        except Exception as e:
            if isinstance(e, InvalidShapefileException): raise
            logger.critical(f"Error procesando cartografía: {str(e)}", exc_info=True)
            raise InvalidShapefileException(f"Error al procesar el mapa: {str(e)}")

geo_service = GeoService()
