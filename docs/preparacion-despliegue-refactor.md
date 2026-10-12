# Preparación del despliegue de las mejoras

Los cambios se organizan en ramas feature y se integran en main. No se modificaron bases de datos reales ni se verificó el despliegue remoto. Un despliegue automático desde main debe contemplar las migraciones pendientes antes de servir esta versión.

## Requisitos

1. Respaldar y verificar la revisión Alembic del entorno destino. `h8i9j0k1l2m3` depende de `g7h8i9j0k1l2` y agrega `layer_features.last_viewed_at`. La revisión siguiente `i9j0k1l2m3n4` agrega `api_key_usage_logs.quota_pending` y unicidad de estadísticas por llave/fecha. Aplicar ambas revisiones pendientes antes de ejecutar esta versión; las consultas ORM incluyen las columnas nuevas.
2. Revisar `docs/migrations/add-feature-last-viewed-at.sql`, generado offline para ese salto concreto. No ejecutar ese SQL directamente si la revisión destino no coincide; utilizar el flujo habitual de Alembic.
3. Configurar `REDIS_URL` y conectividad si hay API keys con `rate_limit_rpm` positivo. Esas llaves devuelven 503 cuando Redis no está disponible. Un valor null mantiene el comportamiento sin límite RPM; cero o negativo no es una configuración admitida.
4. Los perfiles nuevos de Supabase reciben USER. Los administradores deben asignar los privilegios explícitamente; los perfiles existentes conservan sus roles.
5. Verificar login, perfil, sesión revocada, búsquedas y lecturas de capas PUBLIC/PRIVATE con clientes reales. Probar cargas GIS y operaciones de PostgreSQL/PostGIS; las pruebas actuales de persistencia usan mocks y una parte de SQL portable usa SQLite.
6. Revisar `docs/migrations/add-atomic-api-key-usage.sql`. La migración se detiene si existen filas duplicadas de estadísticas por `api_key_id, stat_date`; no borra ni fusiona datos. Resolver esos casos mediante una revisión de datos antes de volver a aplicarla. Esta revisión toma un bloqueo sobre la tabla de estadísticas durante la migración.

## Validación realizada

- 151 pruebas pasaron con Python 3.13.12, incluidas tres integraciones con Redis local aislado, un upsert concurrente sobre SQLite y las pruebas de IA geográfica.
- Importación completa, OpenAPI con 66 rutas y `/health` con HTTP 200 bajo configuración ficticia.
- Compilación de sintaxis y revisión de espacios de Git sin errores.
- Alembic conserva una sola cabeza; se generó SQL offline de la revisión nueva.

Queda pendiente probar con Python 3.12 del runtime de despliegue, servicios externos y PostgreSQL/PostGIS real, especialmente admisiones concurrentes con varias API keys del mismo usuario.

## Comportamiento de cuotas y registro

La admisión reserva cupo mediante una transacción con bloqueo de la fila del usuario, compartido por sus API keys. Se cuentan peticiones exitosas y pendientes en las últimas 24 horas desde su admisión. Una respuesta finalizada con error libera cupo. Una reserva cuyo proceso se interrumpe o cuyo registro final falla sigue contando hasta salir de esa ventana; esta política evita abrir cupo por fallos de logging.

El middleware finaliza el registro antes de enviar las cabeceras, con espera máxima de cinco segundos. Si falla, conserva la respuesta del caso de uso y registra el diagnóstico. La finalización de la misma reserva no duplica métricas; actualiza log, totales y estadísticas dentro de una transacción. En streaming se registra el estado de las cabeceras, sin esperar al cuerpo completo. Los despliegues deben actualizar todos los workers: la versión anterior no utiliza reservas y no puede compartir esta garantía de admisión durante una transición mixta.

## Autenticación y reportes: lote del 12 de octubre

Supabase requiere tokens con exp/sub/issuer/audience válidos. SUPABASE_JWT_SECRET se interpreta como texto literal; no proporcionar una representación Base64 del secreto original. Configurar SUPABASE_JWT_ISSUER si el issuer no coincide con SUPABASE_URL/auth/v1. JWKS tiene caché de diez minutos; recargas por kid desconocido se limitan a una por minuto, por lo que una rotación puede requerir esperar ese intervalo o reiniciar la cache del proceso.

El adaptador legacy login_admin requiere un User activo con el mismo correo y rol ADMIN/SUPER_ADMIN ya asignado. Los roles se toman de User, no del flag is_superadmin de Admin. Los tokens administrativos antiguos con sub=Admin.id requieren iniciar sesión nuevamente. El adaptador sigue siendo interno: este lote no publica una ruta nueva.

Estado y descarga de reportes requieren credenciales del propietario. Actualizar clientes que antes consultaban esas URLs sin autenticación. Estados antiguos sin user_id no se exponen; regenerar sus reportes. El lote no limpia automáticamente PDFs antiguos del disco.

## Escritura de capas y recursos

Modificar/borrar capas y cargar/borrar recursos de descarga requiere propiedad o rol ADMIN/SUPER_ADMIN. Revisar created_by de recursos históricos: si está vacío, solo administración puede modificarlos. El catálogo público omite is_published=false.

Comprobar reemplazos simultáneos de una capa y rollback ante fallos de geometría en PostgreSQL/PostGIS. La escritura bloquea la fila de la capa durante el reemplazo y confirma metadatos/geometrías juntos. DB y storage no tienen commit distribuido: la limpieza posterior puede fallar y dejar archivos huérfanos. Preparar reconciliación de storage antes de asumir limpieza garantizada. Analizadores espaciales requieren bbox EPSG:4326 completo, finito y ordenado; revisar consumidores que envíen coordenadas proyectadas o cruces del antimeridiano.
