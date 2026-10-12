"""Imports historicos de la definicion ORM unica en app.db.models."""

from app.db.models.user import User, UserRole

__all__ = ['User', 'UserRole']
