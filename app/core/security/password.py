"""Gestión de hashing y validación de contraseñas.
Implementa Argon2id como estándar de seguridad.
"""

from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

_pass_hash = PasswordHash((Argon2Hasher(),))


def hash_password(password: str) -> str:
    """Genera un hash seguro mediante el algoritmo Argon2id."""
    return _pass_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Valida una contraseña en texto plano contra su representación persistida."""
    return _pass_hash.verify(plain_password, hashed_password)


def needs_rehash(hashed_password: str) -> bool:
    """Diagnostica si el hash debe actualizarse a una versión más reciente."""
    return _pass_hash.needs_update(hashed_password)
