"""Política de cookies para orígenes locales y de producción."""

from urllib.parse import urlsplit


def is_local_origin(origin: str | None) -> bool:
    if not origin:
        return False
    try:
        parsed = urlsplit(origin)
        return parsed.scheme in {"http", "https"} and parsed.hostname in {
            "localhost", "127.0.0.1", "::1",
        }
    except ValueError:
        return False
