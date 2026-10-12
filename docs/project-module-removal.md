# Retiro del módulo de proyectos

Se retiraron el router de proyectos, sus servicios, repositorios, esquemas y documentación exclusiva. La búsqueda pública y la analítica ahora consultan capas y features GIS. Se retiraron del frontend las páginas administrativas, los componentes del visor y los contratos asociados.

## Conservación de datos

Se conservan `app/db/models/project.py`, `app/db/models/project_asset.py` y sus registros en `app/db/base.py`, junto con todas las migraciones históricas y el SQL de inicialización. Mantener los modelos registrados evita que Alembic interprete las tablas existentes como tablas que deben eliminarse.

No se ejecutaron migraciones ni operaciones de eliminación sobre la base de datos o el almacenamiento remoto. También se conservan los logs históricos y sus totales generales; las estadísticas activas ya no presentan categorías específicas de proyectos.

`removed-project-files.txt` contiene el inventario de archivos retirados. Los archivos estaban versionados y no tenían cambios locales; pueden consultarse en el historial de Git.

## Validación

- Compilación de sintaxis Python de `app` y `tests`: aprobada.
- Imports locales del backend: sin referencias a módulos inexistentes.
- Seis pruebas de búsqueda GIS con sesión simulada: aprobadas.
- Validación posterior del 12 de octubre de 2026: suite completa de 151 pruebas aprobada, import de FastAPI y `/health` 200. No se ejecutaron migraciones ni integraciones con PostgreSQL/PostGIS reales.
