from typing import Any, Dict


class MapControlTools:
    async def activate_layer(self, layer_name: str, visible: bool = True) -> Dict[str, Any]:
        """Activa o desactiva capas del mapa."""
        return {
            "success": True,
            "layer_name": layer_name,
            "visible": visible,
            "map_action": "toggle_layer",
        }

    async def zoom_to_location(self, coordinates: Dict[str, float] | list[float], zoom_level: int = 15) -> Dict[str, Any]:
        """Mueve el mapa y hace zoom a una ubicacion."""
        if isinstance(coordinates, list):
            if len(coordinates) < 2:
                return {"success": False, "error": "Coordenadas invalidas. Usa [longitud, latitud]."}
            coordinates = {"lng": coordinates[0], "lat": coordinates[1]}

        return {
            "success": True,
            "coordinates": coordinates,
            "zoom_level": zoom_level,
            "map_action": "fly_to",
        }

    async def change_basemap(self, basemap_id: str) -> Dict[str, Any]:
        """Cambia la cartografia base del mapa."""
        allowed = {
            "satellite",
            "streets-vector",
            "hybrid",
            "arcgis-osm-3d",
            "arcgis-topographic-3d",
            "arcgis-streets-3d",
            "arcgis-streets-dark-3d",
            "arcgis-imagery-3d",
        }
        aliases = {
            "satelite": "satellite",
            "satellite": "satellite",
            "plano": "streets-vector",
            "calles": "streets-vector",
            "streets": "streets-vector",
            "hibrido": "hybrid",
            "hybrid": "hybrid",
            "3d": "arcgis-osm-3d",
            "osm 3d": "arcgis-osm-3d",
            "topografico": "arcgis-topographic-3d",
            "topo 3d": "arcgis-topographic-3d",
        }

        normalized = str(basemap_id or "").strip().lower()
        target = aliases.get(normalized, normalized)
        if target not in allowed:
            return {
                "success": False,
                "error": f"Mapa base no soportado: {basemap_id}",
                "supported": sorted(allowed),
            }

        return {
            "success": True,
            "basemap_id": target,
            "map_action": "set_basemap",
        }

    async def activate_category(self, category_name: str, visible: bool = True) -> Dict[str, Any]:
        """Activa o desactiva todas las capas de una categoria."""
        return {
            "success": True,
            "category_name": category_name,
            "visible": visible,
            "map_action": "toggle_category",
        }
