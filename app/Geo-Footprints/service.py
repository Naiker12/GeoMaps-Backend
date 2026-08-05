import math
import tempfile
from typing import Any


class FootprintService:
    def dxf_to_geojson(
        self,
        data: bytes,
        filename: str,
        center_lat: float,
        center_lon: float,
        heading: float = 0,
    ) -> dict[str, Any] | None:
        import geopandas as gpd
        from shapely.affinity import rotate
        from shapely.ops import unary_union

        with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        gdf = gpd.read_file(tmp_path)
        if gdf.empty:
            return None

        polygons = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
        if polygons.empty:
            return None

        layer_values = polygons.get("Layer")
        if layer_values is not None:
            preferred = polygons[layer_values.astype(str).str.contains("WALL|HATCH|PLAN|FOOT", case=False, na=False)]
            if not preferred.empty:
                polygons = preferred

        source_count = len(polygons)
        if source_count > 6:
            merged = unary_union([geom for geom in polygons.geometry if geom is not None and not geom.is_empty])
            cleaned = merged.buffer(48).buffer(-48).simplify(8, preserve_topology=True)
            if not cleaned.is_empty:
                polygons = gpd.GeoDataFrame(
                    [{"Layer": "FOOTPRINT_CLEAN", "Text": "", "geometry": cleaned}],
                    geometry="geometry",
                )

        bounds = polygons.total_bounds
        min_x, min_y, max_x, max_y = [float(value) for value in bounds]
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2

        units_to_meters = 0.0254
        meters_per_degree_lat = 111_320
        meters_per_degree_lon = max(1, meters_per_degree_lat * math.cos(math.radians(center_lat)))

        features: list[dict[str, Any]] = []
        for _, row in polygons.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue

            local = rotate(geom, -heading, origin=(center_x, center_y), use_radians=False)
            feature = self._build_feature(
                local=local,
                row=row,
                filename=filename,
                center_x=center_x,
                center_y=center_y,
                center_lat=center_lat,
                center_lon=center_lon,
                units_to_meters=units_to_meters,
                meters_per_degree_lat=meters_per_degree_lat,
                meters_per_degree_lon=meters_per_degree_lon,
                use_primary_measurements=source_count > 6,
                source_count=source_count,
            )
            if feature:
                features.append(feature)

        if not features:
            return None

        return {
            "type": "FeatureCollection",
            "features": features,
            "properties": {
                "source": filename,
                "center": {"latitude": center_lat, "longitude": center_lon},
                "heading": heading,
                "unit": "inch",
                "units_to_meters": units_to_meters,
            },
        }

    def _build_feature(
        self,
        local: Any,
        row: Any,
        filename: str,
        center_x: float,
        center_y: float,
        center_lat: float,
        center_lon: float,
        units_to_meters: float,
        meters_per_degree_lat: float,
        meters_per_degree_lon: float,
        use_primary_measurements: bool,
        source_count: int,
    ) -> dict[str, Any] | None:
        local_rings: list[list[list[float]]] = []
        measurements: list[dict[str, Any]] = []

        if local.geom_type == "Polygon":
            coordinates = [self._to_geo_coords(local.exterior.coords, center_x, center_y, center_lat, center_lon, units_to_meters, meters_per_degree_lat, meters_per_degree_lon)]
            coordinates.extend(self._to_geo_coords(ring.coords, center_x, center_y, center_lat, center_lon, units_to_meters, meters_per_degree_lat, meters_per_degree_lon) for ring in local.interiors)
            geometry = {"type": "Polygon", "coordinates": coordinates}
            local_rings = [self._to_local_meter_coords(local.exterior.coords, center_x, center_y, units_to_meters)]
            local_rings.extend(self._to_local_meter_coords(ring.coords, center_x, center_y, units_to_meters) for ring in local.interiors)
            measurements = self._primary_measurements(local, center_x, center_y, units_to_meters) if use_primary_measurements else self._edge_measurements(local, center_x, center_y, units_to_meters)
        elif local.geom_type == "MultiPolygon":
            coordinates = []
            for poly in local.geoms:
                poly_coords = [self._to_geo_coords(poly.exterior.coords, center_x, center_y, center_lat, center_lon, units_to_meters, meters_per_degree_lat, meters_per_degree_lon)]
                poly_coords.extend(self._to_geo_coords(ring.coords, center_x, center_y, center_lat, center_lon, units_to_meters, meters_per_degree_lat, meters_per_degree_lon) for ring in poly.interiors)
                coordinates.append(poly_coords)
                local_rings.append(self._to_local_meter_coords(poly.exterior.coords, center_x, center_y, units_to_meters))
                measurements.extend(self._primary_measurements(poly, center_x, center_y, units_to_meters) if use_primary_measurements else self._edge_measurements(poly, center_x, center_y, units_to_meters))
            geometry = {"type": "MultiPolygon", "coordinates": coordinates}
        else:
            return None

        centroid = local.centroid
        local_bounds = [
            (float(local.bounds[0]) - center_x) * units_to_meters,
            (float(local.bounds[1]) - center_y) * units_to_meters,
            (float(local.bounds[2]) - center_x) * units_to_meters,
            (float(local.bounds[3]) - center_y) * units_to_meters,
        ]

        return {
            "type": "Feature",
            "geometry": geometry,
            "properties": {
                "source": filename,
                "layer": str(row.get("Layer") or ""),
                "text": str(row.get("Text") or ""),
                "source_feature_count": source_count,
                "is_clean_footprint": use_primary_measurements,
                "area_m2": round(float(local.area) * (units_to_meters**2), 2),
                "centroid": [
                    round((float(centroid.x) - center_x) * units_to_meters, 3),
                    round((float(centroid.y) - center_y) * units_to_meters, 3),
                ],
                "bounds": [round(value, 3) for value in local_bounds],
                "local_rings": local_rings,
                "measurements": measurements,
            },
        }

    def _to_local_meter_coords(self, coords: Any, center_x: float, center_y: float, units_to_meters: float) -> list[list[float]]:
        return [
            [
                (float(x) - center_x) * units_to_meters,
                (float(y) - center_y) * units_to_meters,
            ]
            for x, y, *_rest in coords
        ]

    def _to_geo_coords(
        self,
        coords: Any,
        center_x: float,
        center_y: float,
        center_lat: float,
        center_lon: float,
        units_to_meters: float,
        meters_per_degree_lat: float,
        meters_per_degree_lon: float,
    ) -> list[list[float]]:
        converted = []
        for x, y, *_rest in coords:
            east_m = (float(x) - center_x) * units_to_meters
            north_m = (float(y) - center_y) * units_to_meters
            converted.append([
                center_lon + east_m / meters_per_degree_lon,
                center_lat + north_m / meters_per_degree_lat,
            ])
        return converted

    def _edge_measurements(self, poly: Any, center_x: float, center_y: float, units_to_meters: float) -> list[dict[str, Any]]:
        measurements = []
        coords = list(poly.exterior.coords)
        for start, end in zip(coords, coords[1:]):
            x1, y1 = float(start[0]), float(start[1])
            x2, y2 = float(end[0]), float(end[1])
            dx = (x2 - x1) * units_to_meters
            dy = (y2 - y1) * units_to_meters
            length_m = math.hypot(dx, dy)
            if length_m < 0.75:
                continue
            measurements.append(
                {
                    "length_m": round(length_m, 2),
                    "label": self._format_meters(length_m),
                    "position": [
                        round((((x1 + x2) / 2) - center_x) * units_to_meters, 3),
                        round((((y1 + y2) / 2) - center_y) * units_to_meters, 3),
                    ],
                    "angle": round(math.degrees(math.atan2(dy, dx)), 2),
                }
            )
        return measurements

    def _primary_measurements(self, geom: Any, center_x: float, center_y: float, units_to_meters: float) -> list[dict[str, Any]]:
        minx, miny, maxx, maxy = [float(value) for value in geom.bounds]
        width_m = (maxx - minx) * units_to_meters
        depth_m = (maxy - miny) * units_to_meters
        if width_m <= 0 or depth_m <= 0:
            return []
        return [
            {
                "length_m": round(width_m, 2),
                "label": self._format_meters(width_m),
                "position": [0, round(((maxy - center_y) * units_to_meters) + 1.0, 3)],
                "angle": 0,
                "primary": True,
            },
            {
                "length_m": round(depth_m, 2),
                "label": self._format_meters(depth_m),
                "position": [round(((maxx - center_x) * units_to_meters) + 1.0, 3), 0],
                "angle": 90,
                "primary": True,
            },
        ]

    def _format_meters(self, meters: float) -> str:
        if meters >= 10:
            return f"{meters:.0f} m"
        return f"{meters:.1f} m"


footprint_service = FootprintService()
