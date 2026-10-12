# Revisión del backend — 12 de octubre de 2026

## Alcance

Inventario AST de los 156 archivos Python de app y revisión dirigida de autenticación, reportes, generación PDF, proxy OGC y contratos administrativos. Se conservaron los cambios anteriores del workspace. El inventario completo está en `inventario-revision-2026-10-12.json`: enumera módulos grandes, capturas amplias de excepciones y llamadas candidatas a revisión manual. No equivale a haber probado todos los flujos ni a una auditoría exhaustiva de seguridad.

## Correcciones verificadas

| Área | Problema | Resultado |
| --- | --- | --- |
| JWT | Expiración no obligatoria, issuer/audience externos sin comprobar y decodificación heurística del secreto | Se exige exp/sub; Supabase exige issuer y audience authenticated. El secreto HS256 se usa literalmente. Los nuevos tokens locales incluyen issuer geomaps e iat. Tokens locales históricos sin issuer mantienen compatibilidad si contienen exp/sub. |
| Identidad | Una misma búsqueda mezclaba User.id con User.supabase_id | Tokens locales consultan User.id; externos consultan únicamente User.supabase_id. |
| JWKS | Descarga síncrona desde flujos async, caché de una hora y recargas por cada kid desconocido | Verificación fuera del event loop, caché de diez minutos, bloqueo por proceso y recargas limitadas a una por minuto. Ante fallo de recarga no se reutilizan llaves vencidas. Se verifican ES256 y RS256 además de HS256. |
| Login administrativo legacy | Token y sesión con ID de Admin, pero dependencias basadas en User; respuesta construida con un esquema incompatible | Credenciales de Admin se vinculan por correo a un User activo con rol administrativo ya asignado. Token, sesión y perfil usan ese User; no se crean perfiles ni se promueven roles automáticamente. Se conserva el esquema AuthResponse existente. No se agregó un endpoint nuevo de login. |
| Roles | Los esquemas admitían EDITOR y otros roles que el enum de PostgreSQL no contiene | UserCreate/UserUpdate validan UserRole antes de consultar o escribir en la base. Hash de contraseña administrativa fuera del event loop. |
| Reportes | Estado y descarga sin autenticación ni propietario | Ambas rutas requieren identidad activa y propietario guardado en Redis. Reportes ajenos o antiguos sin propietario responden 404. IDs inválidos responden 422. Fallos de Redis controlados devuelven 503. |
| Trabajo en segundo plano | Reutilizaba la sesión DB de la petición | El trabajo abre y cierra su propia SessionLocal. Los timestamps usan UTC; los errores públicos no incluyen excepciones internas. |
| PDF | Linux ejecutaba render síncrono dentro de función async | El render se delega a un hilo en todos los sistemas. |
| OGC | Leía todo el cuerpo antes de comprobar el límite; DNS síncrono y URLs inválidas podían provocar 500 | Lectura por chunks con parada al superar el límite; DNS fuera del event loop; URLs/puertos inválidos responden 400; errores de conexión públicos no revelan detalles internos. |

JWT se contrastó con documentación primaria de Supabase y Authlib: https://supabase.com/docs/guides/auth/jwts y https://docs.authlib.org/en/latest/jose/jwt.html. Si SUPABASE_URL usa un dominio diferente del issuer del JWT, configurar SUPABASE_JWT_ISSUER explícitamente con el issuer auténtico del proyecto.

## Validación

- 114 pruebas aprobadas en Python 3.13.12, incluidas firmas reales HS256/ES256/RS256, caché JWKS, identidad administrativa, privacidad de reportes y respuesta OGC acotada.
- Sintaxis de app/tests/alembic compilada; git diff --check sin errores.
- Aplicación completa: OpenAPI con 66 rutas y /health HTTP 200 bajo configuración ficticia.
- Alembic conserva una sola cabeza i9j0k1l2m3n4; este lote no agregó migraciones.
- No se conectó a PostgreSQL/Supabase reales ni se desplegó la aplicación. La generación PDF se prueba mediante un render simulado; no se afirma QA visual de PDFs reales.

## Pendientes priorizados

1. Validar reservas concurrentes y migraciones en PostgreSQL real, incluyendo duplicados históricos y distintas llaves del mismo usuario. Probar Python 3.12 del entorno destino.
2. Verificar login/rotación de llaves contra Supabase real y actualizar el frontend para enviar credenciales al estado y descarga de reportes. Los reportes antiguos de Redis sin propietario necesitan regenerarse; TTL actual una hora.
3. El proxy OGC valida DNS antes de HTTP, pero el transporte vuelve a resolver el host: queda pendiente el endurecimiento frente a DNS rebinding. No se verificó un exploit ni se presenta la validación actual como protección completa contra SSRF.
4. Revisar ciclo de vida de PDFs temporales y trabajos interrumpidos; Redis expira el estado pero no elimina los archivos del disco. Validar concurrencia del uso de Matplotlib durante render.
5. Separar responsabilidades en cartografía/generator.py, ia/agent_service.py y report/report_engine.py, con pruebas de salida antes de extraer lógica. El inventario detecta 69 capturas amplias de Exception: son candidatos, no 69 fallos confirmados.
6. Revisar errores de analizadores espaciales, SQL dinámico y permisos de escritura/propiedad. Las lecturas anónimas corregidas no establecen aislamiento por propietario para todos los usuarios autenticados.

Las migraciones preparadas anteriormente siguen sin aplicar a bases reales. Antes de desplegar, seguir `preparacion-despliegue-refactor.md` y verificar estos cambios de contrato.

## Continuación: escritura, transacciones y análisis espacial

Se corrigieron permisos de modificación y eliminación de capas, y de carga/eliminación de recursos de descarga. La política exige cuenta activa y propietario coincidente, o rol ADMIN/SUPER_ADMIN. Recursos históricos sin created_by requieren administración. En capas, actor es obligatorio en los métodos de escritura del servicio, y la comprobación precede al parseo, subida, borrado de geometrías y borrado de archivos. HTTP traduce rechazo a 403 y capa ausente al eliminar a 404. La política no restringe las lecturas autenticadas por propietario.

Las capas se crean y reemplazan dentro de una unidad de trabajo: los repositorios pueden diferir commit, y el servicio confirma una vez después de metadatos y geometrías. Las modificaciones/borrados bloquean la fila de la capa con FOR UPDATE y refrescan datos previamente cargados, evitando reemplazos que mezclen snapshots anteriores. Si la carga nueva falla, no se borran geometrías antiguas. Si falla la persistencia antes de commit, se revierte la transacción y se intenta retirar el archivo nuevo; después de commit no se elimina el archivo confirmado ante un fallo de refresh. El archivo antiguo se retira después de confirmar el reemplazo. Las eliminaciones de capas y descargas confirman DB antes de limpiar storage. La limpieza es best effort: un fallo puede dejar archivos huérfanos y requiere una tarea de reconciliación, no constituye una transacción distribuida con Supabase. El bloqueo de una capa dura durante la carga del archivo; debe verificarse su latencia y concurrencia en PostgreSQL real.

La inserción de geometrías ya no interpola WKT dentro de SQL: utiliza ST_GeomFromText con un parámetro. Los helpers espaciales también parametrizan nombres de campos JSON, validan bbox completo/finito/ordenado en EPSG:4326 y límites de 1–500. El filtro numérico reconoce valores con signo, decimales y notación científica, y excluye texto malformado antes del cast. Los errores SQLAlchemy de la clase base hacen rollback y se propagan en lugar de simular datos vacíos. Los analizadores especializados y otros fallbacks siguen requiriendo revisión.

El catálogo público de descargas aplica show_in_public=true e is_published=true, excluyendo borradores que antes podían mostrarse. Las consultas administrativas conservan su comportamiento.

Validación de esta continuación: **137 pruebas aprobadas** (23 nuevas), sintaxis compilada y git diff --check sin errores. La aplicación conserva 66 rutas en OpenAPI y /health devuelve 200 en configuración ficticia. No hay migraciones nuevas en este lote. Las pruebas de permisos incluyen HTTP y las de transacciones simulan DB/storage y comprueban orden, commits diferidos, rollback y compensación; no equivalen a integración PostgreSQL/PostGIS ni a comprobar fallos de red reales.
