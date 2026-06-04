"""Builds cartography payloads from persisted GIS layers."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.repositories.layer_repository import LayerRepository
from app.schemas.cartografia import CartografiaGenerateRequest


class CartografiaPayloadBuilder:
    def __init__(self, repository: LayerRepository):
        self.repository = repository

    async def build(self, request: CartografiaGenerateRequest) -> dict[str, Any]:
        layer = await self.repository.get(request.layer_id)
        if not layer:
            raise HTTPException(status_code=404, detail="Capa principal no encontrada")

        geojson = await self.repository.get_features_as_geojson(request.layer_id)
        features = self._filter_features(geojson.get("features", []), request)
        attributes = self._resolve_attributes(features, request.attribute_fields)
        cleaned_features = self._project_attributes(features, attributes)

        secondary_payload = await self._build_secondary_payload(request)

        return {
            "title": request.title,
            "layer_id": request.layer_id,
            "layer_name": layer.name,
            "feature_count": len(cleaned_features),
            "secondary_layer": secondary_payload,
            "attributes": attributes,
            "filters": {
                "data_scope": request.data_scope,
                "field": request.filter_field,
                "value": request.filter_value,
            },
            "geojson": {
                "type": "FeatureCollection",
                "features": cleaned_features,
            },
        }

    async def _build_secondary_payload(self, request: CartografiaGenerateRequest) -> dict[str, Any] | None:
        if not request.secondary_layer_id:
            return None

        secondary_layer = await self.repository.get(request.secondary_layer_id)
        if not secondary_layer:
            raise HTTPException(status_code=404, detail="Segunda capa no encontrada")

        secondary_geojson = await self.repository.get_features_as_geojson(request.secondary_layer_id)
        secondary_features = secondary_geojson.get("features", [])
        return {
            "layer_id": request.secondary_layer_id,
            "layer_name": secondary_layer.name,
            "feature_count": len(secondary_features),
            "geojson": {
                "type": "FeatureCollection",
                "features": secondary_features,
            },
        }

    def _filter_features(
        self,
        features: list[dict[str, Any]],
        request: CartografiaGenerateRequest,
    ) -> list[dict[str, Any]]:
        if request.data_scope != "filtered":
            return features
        if not request.filter_field or request.filter_value in (None, ""):
            return features

        expected = str(request.filter_value).strip()
        exact_matches = [
            feature
            for feature in features
            if str((feature.get("properties") or {}).get(request.filter_field, "")).strip() == expected
        ]
        route_code = self._route_code_from_matches(exact_matches)
        if route_code:
            route_matches = [
                feature
                for feature in features
                if str((feature.get("properties") or {}).get("cod_ruta", "")).strip() == route_code
            ]
            if route_matches:
                return route_matches

        return exact_matches

    def _route_code_from_matches(self, features: list[dict[str, Any]]) -> str | None:
        for feature in features:
            props = feature.get("properties") or {}
            has_route_fields = any(key in props for key in ("sentido", "SENTIDO", "cod_ruta"))
            route_code = str(props.get("cod_ruta", "")).strip()
            if has_route_fields and route_code:
                return route_code
        return None

    def _resolve_attributes(
        self,
        features: list[dict[str, Any]],
        requested_attributes: list[str],
    ) -> list[str]:
        if requested_attributes:
            return requested_attributes

        discovered: list[str] = []
        for feature in features[:25]:
            for key in (feature.get("properties") or {}).keys():
                if key not in discovered:
                    discovered.append(key)
                if len(discovered) >= 12:
                    return discovered
        return discovered

    def _project_attributes(
        self,
        features: list[dict[str, Any]],
        attributes: list[str],
    ) -> list[dict[str, Any]]:
        if not attributes:
            return features

        projected = []
        for feature in features:
            props = feature.get("properties") or {}
            projected.append({
                **feature,
                "properties": {key: props.get(key) for key in attributes if key in props},
            })
        return projected
