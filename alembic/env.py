import asyncio
import logging
from logging.config import fileConfig

import sqlalchemy
from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Este es el objeto Config de Alembic, que proporciona
# acceso a los valores dentro del archivo .ini en uso.
config = context.config

# Interpretar el archivo de configuración para el registro de Python.
# Esta línea configura básicamente los registradores.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Añade el objeto MetaData de tu modelo aquí
# para soporte de 'autogenerate'
# de myapp import mymodel
# target_metadata = mymodel.Base.metadata
from app.db.base import Base
target_metadata = Base.metadata

# otros valores de la configuración, definidos por las necesidades de env.py,
# pueden ser adquiridos desde aquí:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

def include_object(object, name, type_, reflected, compare_to):
    """
    Indica si Alembic debe incluir el objeto en la migración.
    Ignoramos la tabla 'spatial_ref_sys' de PostGIS para evitar que intente borrarla.
    """
    if type_ == "table" and name == "spatial_ref_sys":
        return False
    return True

def run_migrations_offline() -> None:
    """Ejecuta las migraciones en modo 'offline'.

    Configura el contexto con solo una URL
    y no un Motor, aunque un Motor también es aceptable
    aquí. Al omitir la creación del Motor, ni siquiera necesitamos
    que un DBAPI esté disponible.

    Las llamadas a context.execute() aquí emiten la cadena dada a la
    salida del script.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Ejecuta las migraciones en modo 'online'.

    En este escenario necesitamos crear un Motor (Engine)
    y asociar una conexión con el contexto.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
