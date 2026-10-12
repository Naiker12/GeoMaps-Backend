# Organización de ramas del backend

Los cambios de la revisión se organizan en ramas `feature/`, sin prefijo codex:

- `feature/Seguridad`: autenticación, identidad, permisos, API keys, cuotas y middleware.
- `feature/Mapa`: capas, búsqueda GIS, validación espacial, OGC y migración de visualizaciones.
- `feature/IA`: contexto espacial, métricas PostGIS y presentación de resultados.
- `feature/Descargas`: publicación, almacenamiento, transacciones de descargas y reportes.
- `feature/Proyectos`: retiro del módulo de proyectos y actualización de analítica GIS; se conservan tablas, modelos y datos.
- `feature/Documentacion`: inventario, instrucciones de pruebas y preparación de despliegue.

Las ramas se crean de forma secuencial sobre la integración local de las anteriores para conservar dependencias compartidas. Cada una tiene su commit funcional y se integra en main mediante un commit de merge. No son ramas independientes basadas todas en el mismo commit inicial.

Validación previa: 151 pruebas, compileall, un único head Alembic. Validación final: suite completa, imports/OpenAPI, health y diferencias sin errores de espacios.

Subir código y fusionar no aplica las migraciones: `h8i9j0k1l2m3` e `i9j0k1l2m3n4` requieren la preparación documentada en `preparacion-despliegue-refactor.md`. El entorno debe disponer de Redis para llaves con límite RPM. El repositorio incluye configuración Render; el estado del despliegue remoto se verifica por separado.
