# Integración del backend — 14 de octubre de 2026

Cambios separados por responsabilidad y fusionados con commits de merge en main:

- feature/Seguridad: retiro de API keys de terceros, dependencias de autenticación y eliminación de adaptadores obsoletos.
- feature/Almacenamiento: conexiones Supabase y protección de tablas no mapeadas en Alembic.
- feature/IA: conexiones cifradas, descubrimiento de modelos, modelo predeterminado, streaming, herramientas, memoria y límites. Revisión j0k1l2m3n4o5.
- feature/Proyectos: retiro del ORM y almacenamiento, script de respaldo y revisión k1l2m3n4o5p6.
- feature/Cartografia: ajuste de espacio del encabezado de salida.
- feature/Reportes: escape Typst y prueba de compilación PDF.
- feature/Documentacion: limpieza de documentación retirada, icono y actualización de configuración y alcance de pruebas.

## Verificación

193 pruebas unittest aprobadas, incluidas las pruebas reales del compilador Typst. git diff --check sin incidencias. La suite simula servicios externos; no sustituye una prueba de integración contra PostgreSQL/PostGIS real.

## Operación

Configurar AI_PROVIDER_ENCRYPTION_KEY en el servidor antes de guardar claves de proveedores. No publicar .env ni respaldos privados. El código publicado no ejecuta migraciones por sí mismo. La revisión de proyectos requiere un respaldo verificado generado mediante scripts/retire_projects.py; un alembic upgrade head sin ese respaldo se detiene. Aplicar j0k1l2m3n4o5 por separado si aún no corresponde retirar proyectos. No usar CASCADE ni eliminar tablas por ausencia de metadatos ORM.
