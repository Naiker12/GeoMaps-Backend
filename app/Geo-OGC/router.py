"""Secure OGC proxy endpoints for WMS/WFS requests."""

from __future__ import annotations

import ipaddress
import socket
from typing import Dict
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.api.deps import get_current_active_user
from app.db.models.user import User

router = APIRouter()

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443, 8080, 8443}
MAX_PROXY_BYTES = 5 * 1024 * 1024


def _validate_public_url(raw_url: str) -> str:
    parsed = urlparse(raw_url.strip())

    if parsed.scheme not in ALLOWED_SCHEMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se permiten URLs http o https.",
        )
    if not parsed.hostname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La URL del servicio no tiene un host valido.",
        )
    if parsed.username or parsed.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se permiten credenciales en la URL.",
        )

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Puerto no permitido para servicios OGC.",
        )

    try:
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo resolver el host del servicio.",
        )

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La URL apunta a una red no permitida.",
            )

    return urlunparse(parsed)


def _build_upstream_url(base_url: str, incoming_params: Dict[str, str]) -> str:
    parsed = urlparse(base_url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in incoming_params.items():
        if key.lower() == "url":
            continue
        params[key] = value

    if not any(key.upper() == "REQUEST" for key in params):
        params["REQUEST"] = "GetCapabilities"

    return urlunparse(parsed._replace(query=urlencode(params, doseq=True)))


@router.get("/proxy")
async def proxy_ogc_request(
    request: Request,
    url: str = Query(..., min_length=8, max_length=2048),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    """Proxy a bounded OGC request after validating the target URL."""

    safe_url = _validate_public_url(url)
    upstream_url = _build_upstream_url(safe_url, dict(request.query_params))

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            upstream = await client.get(
                upstream_url,
                headers={"User-Agent": "GeoMaps-OGC-Proxy/1.0"},
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"No se pudo conectar con el servicio OGC: {exc}",
        )

    if len(upstream.content) > MAX_PROXY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="La respuesta del servicio OGC excede el limite permitido.",
        )

    content_type = upstream.headers.get("content-type", "application/xml")
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=content_type.split(";")[0],
    )
