"""Política compartida para modificaciones de recursos creados por usuarios."""

import uuid

from app.db.models.user import User, UserRole


def ensure_resource_owner(actor: User, owner_id: uuid.UUID | None) -> None:
    """Recursos sin propietario requieren administración explícita."""
    if not actor.is_active:
        raise PermissionError("La cuenta de usuario está desactivada")
    if actor.role in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        return
    if owner_id is None or actor.id != owner_id:
        raise PermissionError("No tienes permisos para modificar este recurso")
