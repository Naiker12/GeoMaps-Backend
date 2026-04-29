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

    async def zoom_to_location(self, coordinates: Dict[str, float], zoom_level: int = 15) -> Dict[str, Any]:
        """Mueve el mapa y hace zoom a una ubicacion."""
        return {
            "success": True,
            "coordinates": coordinates,
            "zoom_level": zoom_level,
            "map_action": "fly_to",
        }
