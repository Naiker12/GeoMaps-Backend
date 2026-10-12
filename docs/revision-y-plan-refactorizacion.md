# Revisión y plan de refactorización de GeoMaps

Fecha: 11 de octubre de 2026. Repositorios: `D:\GeoMaps-Backend` y `D:\GeoMaps-Frontend`.

## Alcance y límites

Revisión estática de estructura, arranque, modelos, autenticación, clientes HTTP y módulos principales. No equivale a una auditoría exhaustiva ni a una reproducción de todos los errores de producción. No se modificó el comportamiento de la aplicación durante esta revisión.

Ambos repositorios estaban limpios al comenzar. No se encontraron archivos AGENTS.md en los archivos listados ni en las ubicaciones raíz consultadas. No se identificó una suite de pruebas propia en el inventario consultado.

Validación intentada:

- Backend: Python, python3, py y uv no están disponibles en PATH. No se pudo ejecutar importación de FastAPI, pruebas ni migraciones.
- Frontend: Node v24.19.0 disponible; pnpm ausente en PATH; dependencias locales ausentes. `npm.cmd run lint` falla porque falta eslint; `npm.cmd run build` falla porque falta tsc. Esto es un bloqueo de entorno, no evidencia de errores de TypeScript.
- PowerShell bloquea npm.ps1; npm.cmd permite invocar los scripts sin cambiar la política del sistema.

## Hallazgos prioritarios

| Prioridad | Evidencia | Problema e impacto | Acción y criterio de aceptación |
| --- | --- | --- | --- |
| Alta | Backend `app/api/deps.py`, `get_user_from_api_key`; `app/db/models/api_key.py` | Las llaves tienen expires_at y rate_limit_rpm, pero la autenticación solo filtra hash y estado activo y aplica cuota diaria. No valida vencimiento ni aplica el límite por minuto configurable. | Rechazar llaves vencidas; definir y aplicar política RPM. Probar límites, vencimiento y revocación con reloj controlado. |
| Alta | Backend `app/api/deps.py`, `get_current_user_optional`; `app/api/v1/layers.py`, `list_layers` | La autenticación opcional devuelve usuarios sin comprobar is_active. La consulta de capas fuerza PUBLIC solo cuando no hay usuario. Un usuario desactivado puede continuar siendo tratado como autenticado en este flujo. | Centralizar comprobación de actividad y política de acceso. Probar usuario inactivo con JWT y API key en listado y detalle de capas. |
| Alta | Frontend `src/store/Auth-Context.tsx`, rama storedApiKey; `src/services/Auth-Service.ts`, getMe; backend `app/api/v1/auth.py`, get_my_profile | El frontend intenta restaurar perfil con API key vía /auth/me. Esa ruta utiliza la dependencia de core/security que acepta JWT o cookie, no API key. Sin esos tokens, falla y el frontend elimina la llave guardada. | Definir contrato de identidad para API keys; alinear cliente y servidor. Verificar restauración usando exclusivamente API key. |
| Media | Frontend `src/store/Auth-Context.tsx`, callback onAuthStateChange; `src/services/Api-Client.ts` | SIGNED_IN espera refreshProfile dentro del callback; refreshProfile e interceptor vuelven a consultar getSession. Es un flujo reentrante que debe verificarse por posibles bloqueos o carreras. | Programar sincronización fuera del callback y controlar peticiones concurrentes. Validar login, logout, cambio de cuenta y montaje bajo StrictMode. |
| Media | Frontend `src/lib/supabase.ts`, customStorage y lock | El almacenamiento selecciona prefijo según URL, pero lee también la sesión del otro prefijo. La separación admin/user no está garantizada. El lock personalizado ejecuta directamente la función y elimina la exclusión mutua. | Definir si hay una sesión única o aislamiento real. Verificar navegación, callback OAuth, múltiples pestañas y renovación del token. |
| Media | Backend `app/domain/models/user.py` y `app/db/models/user.py` | Dos modelos ORM declaran users sobre la misma Base; ocurre también con otros modelos legacy. No se encontraron consumidores de domain.models en app/alembic mediante búsqueda textual. El conflicto de registro es potencial si ambas variantes se importan. | Inventariar consumidores y consolidar modelos en db/models. Verificar metadatos y Alembic antes de retirar archivos. |
| Media | Backend `app/api/v1/auth.py`, _is_local_origin | La decisión sobre cookies usa búsqueda de subcadenas localhost/127.0.0.1 en Origin. Un hostname que incluya ese texto puede clasificarse como local. | Parsear la URL y comparar hostname exacto con lista local. Probar orígenes locales, producción y hostnames engañosos. |
| Media | Backend `app/api/deps.py`, get_current_user_optional | Un except Exception convierte también errores de base de datos en usuario anónimo. | Capturar solo errores esperados de credenciales; conservar observabilidad y respuesta adecuada ante fallos de infraestructura. |
| Baja | Backend `app/services/projects/service.py`, create_project | Argumento mutable por defecto files=[]. En el cuerpo observado no se modifica la lista, pero el contrato facilita errores futuros. | Usar None o colección inmutable y tipar sesión/dependencias. |

Estos hallazgos derivan del código leído; las hipótesis de concurrencia y conflicto ORM requieren reproducción. Las rutas administrativas que usan get_current_active_user sí tienen verificación de actividad; el problema no afecta por igual a todas las rutas.

## Estructura objetivo y nombres

Mantener una arquitectura modular por capas próxima a la actual para reducir el alcance de los cambios:

```text
backend/app/
  api/v1/              routers y dependencias HTTP
  core/                configuración, seguridad, logging
  db/models/           única fuente de modelos ORM
  schemas/             contratos de entrada/salida
  services/<feature>/  casos de uso y reglas de negocio
  repositories/        consultas y persistencia
  infrastructure/      proveedores HTTP, IA, storage, correo y caché

frontend/src/
  app/                 rutas, providers y layouts
  admin/               páginas y composición administrativa
  features/<feature>/  componentes, hooks, servicios, tipos y utilidades del módulo
  components/ui/       primitivas visuales compartidas
  core/types/          contratos usados por varios módulos
  lib/                 integraciones compartidas y cliente HTTP
  store/               contextos compartidos durante la transición
```

Python: carpetas y módulos snake_case; clases PascalCase. Frontend: carpetas y archivos kebab-case; símbolos de componentes PascalCase; hooks use-*.ts. Usar nombres de negocio explícitos en lugar de Page.tsx/Form-Tabs.tsx cuando no sean una convención del framework. Unificar nombres técnicos en inglés y mantener textos de interfaz en español.

Ejemplos de migración: `API-Key-Service.ts` → `api-key-service.ts`; `Auth-Context.tsx` → `auth-context.tsx`; `features/ia` → `features/ai`; `admin/components/proyectos` → `admin/components/projects`; `features/map/components/Project` → `features/map/components/project`.

Los nombres internos se pueden cambiar; rutas públicas /ia, /cartografia, /projects, claves de almacenamiento y tablas requieren compatibilidad explícita. Renombres que solo cambian mayúsculas deben pasar por un nombre temporal para que Git los registre correctamente en Windows.

Los archivos como app/services/project_service.py son reexportaciones de compatibilidad, no necesariamente lógica duplicada. Mantenerlos hasta migrar sus consumidores y luego retirarlos. Evaluar application/, domain/ e infrastructure/repositories/ por uso real antes de consolidarlos; evitar conservar dos arquitecturas para la misma responsabilidad.

## Plan de ejecución

1. **Preparar una base reproducible.** Configurar Python y entorno virtual compatibles con runtime.txt/.python-version; instalar requirements.txt. Instalar frontend usando pnpm y pnpm-lock.yaml con lockfile congelado. Documentar variables con ejemplos sin secretos. Ejecutar lint, build, importación de app y revisión de migraciones sobre una base de prueba. Guardar resultados antes de editar.
2. **Corregir autenticación y contratos.** Resolver vencimiento de llaves, usuarios inactivos, perfil por API key y configuración de cookies. Elegir una política común para JWT/API key/fallback. Agregar pruebas de regresión enfocadas en esos fallos, sin mezclar renombres en esta etapa.
3. **Estabilizar sesión del frontend.** Extraer sincronización y estado de autenticación del provider; eliminar estados globales compartidos cuando produzcan carreras; controlar resultados obsoletos y errores. Resolver estrategia de storage/lock y pruebas manuales de varias pestañas.
4. **Consolidar backend por módulo.** Empezar por auth y API keys, luego proyectos, capas y descargas. Unificar modelos y dependencias; trasladar routers legacy a api/v1 con los mismos prefijos y contratos. Migrar imports antes de eliminar wrappers. Comparar OpenAPI antes/después.
5. **Aplicar SOLID a responsabilidades concretas.** Inyectar repositorios, storage y cliente IA en servicios mediante interfaces pequeñas (Protocol cuando aporta valor). Construir dependencias concretas en la composición de la aplicación. Los routers traducen HTTP, servicios coordinan casos de uso, repositorios consultan datos y adaptadores hablan con proveedores. Evitar introducir clases para funciones simples.
6. **Dividir módulos complejos.** Backend: cartografia/generator.py, ia/agent_service.py y report/report_engine.py. Frontend: ai-chart-renderer.tsx, Form-Tabs.tsx, Project-Modal.tsx, API-Modal.tsx, Layer-Context.tsx y use-ai-chat.ts. Separar validación, transformación de datos, efectos y presentación según sus responsabilidades; el número de líneas es una señal, no una regla automática.
7. **Normalizar nombres e imports.** Trabajar por feature; revisar rutas, imports dinámicos, archivos públicos y sensibilidad a mayúsculas. Mover servicios exclusivos al módulo correspondiente; dejar cliente HTTP y contratos compartidos en ubicaciones comunes. Sustituir any por tipos concretos o unknown con validación, empezando por errores HTTP y límites externos.
8. **Cerrar y documentar.** Ejecutar verificaciones de cada módulo, lint/build global y smoke tests de login, visor 2D/3D, proyectos, capas, uploads, descargas, IA y reportes. Actualizar README e inventario de funciones. Incorporar CI para las verificaciones reproducibles.

## Aplicación de SOLID

- **Responsabilidad única:** separar sesión, transporte HTTP, renderizado de gráficas, composición de reportes y persistencia.
- **Abierto/cerrado:** adaptadores intercambiables de IA, storage y renderizado cuando existan alternativas reales.
- **Sustitución:** repositorios y proveedores deben preservar retornos, errores y comportamiento al reemplazarse; comprobarlo con contratos.
- **Segregación de interfaces:** contratos pequeños para lectura, escritura, subida y envío; evitar repositorios universales que mezclen todo.
- **Inversión de dependencias:** servicios reciben colaboradores en vez de crearlos internamente; FastAPI y providers hacen la composición.

## Criterios para aceptar cada etapa

- Cambios pequeños por módulo, con diff revisable y comportamiento esperado explícito.
- Sin cambios accidentales en endpoints, esquemas, permisos, tablas o migraciones históricas.
- Pruebas de regresión para errores corregidos; verificación de importaciones y compilación después de movimientos.
- Migraciones nuevas solo si cambia el esquema; no reescribir migraciones ya aplicadas.
- Build/lint y pruebas ejecutadas con resultados reales, sin presentar bloqueos de entorno como validaciones exitosas.

Primer lote recomendado: entorno reproducible y correcciones de autenticación/API keys. La reorganización de carpetas viene después de esa base verificable.

## Avance: primer lote implementado

Se centralizó resolución JWT y comprobación de cuenta activa en app/core/security/identity.py, compartida por ambas dependencias de seguridad. La autenticación opcional ya no oculta fallos de persistencia ni acepta cuentas desactivadas. El fallback JWT/API key solo ocurre ante 401 y con llave explícita; un rechazo por cuenta inactiva conserva el 403.

Las API keys vencidas se rechazan antes de consultar cuota o actualizar último uso. last_used utiliza UTC con zona horaria. GET /auth/me acepta la dependencia unificada; las modificaciones de perfil conservan JWT/cookie. La política de cookies compara hostnames locales exactos. UserProfileUpdate separa campos personales de UserUpdate administrativo; el servicio existente ya filtraba campos personales, por lo que este cambio hace explícito el contrato de entrada.

Frontend: contexto/hook separados de auth-provider.tsx, consumidores migrados, ApiError tipado, sincronización fuera del callback de Supabase, conservación de llaves ante fallos transitorios y corrección del nombre de usuario en login. Se conserva el alcance de los cambios de este lote; la política RPM, modelos legacy, estado global de sesión y refactorización de módulos grandes siguen pendientes.

Entorno: dependencias frontend instaladas con lockfile congelado. Python 3.12.8 y requirements.txt preparados en una carpeta temporal, sin instalación global. La sintaxis de app/ y tests/ pasó compileall; diez comprobaciones de hostnames de cookies pasaron usando el módulo independiente.

La suite de trece pruebas de autenticación está en tests/test_authentication.py, pero Windows impidió cargar la extensión nativa de Pydantic mediante Control de aplicaciones, incluso fuera del aislamiento. No se afirma que la suite haya pasado. Se necesita un entorno que permita cargar las dependencias nativas para ejecutar unittest, arrancar FastAPI y verificar migraciones sobre una base de prueba.

Lint dirigido del frontend pasó en auth-context.ts, auth-provider.tsx, Api-Client.ts, api-error.ts y Login-Form.tsx. En la primera medición global se encontraron 571 errores y 35 advertencias en 151 archivos, predominantemente no-explicit-any y reglas de hooks. La comparación contra HEAD mostró mejoras en el contexto (12 → 1 errores antes de separar el hook) y cliente HTTP (5 → 4 antes de sustituir los any restantes); esos archivos ahora pasan lint dirigido.

La medición final de ESLint registra **565 errores y 35 advertencias en 148 archivos**. Hay 430 usos explícitos de any pendientes; también aparecen 43 errores set-state-in-effect, 37 variables sin uso y 24 errores de refs, además de otras reglas. No se desactivaron reglas para aprobar este lote. `tsc -b` pasó con la estructura final de autenticación.

Orden siguiente: ejecutar la suite del backend en un entorno compatible; resolver RPM/cuotas y concurrencia de sesión; después limpiar hooks por feature, priorizando mapa e IA, y consolidar modelos/imports legacy. La deuda global de ESLint continúa abierta.

**Build final del frontend aprobado:** npm.cmd run build terminó con código 0 sobre los renombres finales; Vite transformó 15.913 módulos y terminó en 3m 59s. Permanecen advertencias por chunks superiores a 500 kB y por ErrorPage importado de forma estática y dinámica. No se probó login real contra Supabase ni se aplicaron migraciones o despliegues.

## Segundo lote: almacenamiento y verificación del backend

El 11 de octubre de 2026 se corrigieron las operaciones de `app/services/storage/service.py`: carga, URL pública, URL firmada, eliminación y descarga delegan las llamadas síncronas del SDK de Supabase a `run_in_threadpool`, evitando bloquear el event loop durante la espera de red. La carga lee como máximo `MAX_FILE_SIZE + 1` bytes antes de validar el tamaño, manteniendo el límite de 50 MB y los contratos existentes.

Se agregaron cinco regresiones en `tests/test_storage.py`. La suite completa de 24 pruebas pasó en el entorno local `venv` (Python 3.13.12), incluidas las trece de autenticación anteriormente pendientes y las seis de búsqueda. Los clientes externos y la base de datos se simulan; este resultado no valida conexiones reales, arranque completo ni migraciones.

Pendientes de este módulo: el análisis previo de metadatos de descargas todavía lee el archivo completo y ejecuta pandas/GeoPandas en el event loop. Requiere una mejora propia con pruebas de formatos y manejo HTTP del límite de tamaño. El segundo lote se limita al servicio compartido de almacenamiento; no constituye una auditoría exhaustiva.

## Tercer lote: análisis y carga de descargas

Se resolvió el pendiente de análisis previo: `DownloadStorageService.analyze_file` limita la lectura a 50 MB más un byte de detección, rechaza el exceso con `FileTooLargeError` y restaura el cursor incluso si falla. El procesamiento de CSV, GeoJSON y ZIP se realiza en el thread pool. CSV usa un buffer en memoria y bloques de 10.000 filas, evitando temporales y un DataFrame completo. GeoJSON ignora geometrías malformadas al reunir tipos sin perder el conteo de registros. Los fallos de análisis opcional conservan el tamaño y ahora dejan un registro de diagnóstico.

La ruta de carga traduce el exceso de tamaño a HTTP 413 antes de subir o actualizar metadatos, y valida nombres ausentes sin provocar un error de atributo. Once regresiones adicionales cubren el análisis, limpieza de temporales y peticiones HTTP de rechazo y éxito. Pasaron las 35 pruebas del backend. ZIP usa un lector simulado; quedan pendientes verificaciones con archivos GIS reales y servicios externos. El límite se aplica al procesamiento del archivo recibido, no limita el cuerpo multipart antes de que FastAPI lo reciba.

## Cuarto lote: API keys, modelos, autenticación y búsqueda

- RPM ahora se aplica cuando `rate_limit_rpm` está configurado. Redis cuenta las peticiones admitidas en ventanas de 60 segundos iniciadas por la primera petición. El script Lua combina contador y expiración en una operación atómica, siguiendo el patrón documentado por Redis: https://redis.io/docs/latest/commands/incr/. Rechazar no extiende la ventana; 429 incluye Retry-After. `null` conserva llaves sin límite RPM. Cero y valores negativos se rechazan en los esquemas; registros históricos con esos valores devuelven 503. Redis inaccesible también produce 503 en llaves limitadas; requiere REDIS_URL operativo.
- Cuotas: se mantiene el contrato existente de diez peticiones exitosas en las últimas 24 horas. La constante se comparte con las estadísticas; las ventanas SQL pasan como parámetros timedelta, sin interpolación de SQL. Revocación y fechas de estadísticas usan UTC.
- Los módulos históricos de User, UserSession y Admin reexportan los modelos únicos de db/models. Conservan sus imports y evitan registrar dos tablas iguales. No cambian esquemas ni migraciones.
- Los errores globales conservan el diagnóstico en logs y responden con un mensaje genérico. Los handlers ya no reflejan cualquier Origin con credenciales: aceptan configuración y orígenes locales coherentes con el middleware.
- Nuevos perfiles Supabase reciben USER; el dominio del correo y user_metadata no otorgan administración. No se modifica el rol de perfiles existentes. Identidades sin UUID/correo válido se rechazan; las cuentas inactivas se detectan antes de mutarlas. Los errores de flush revierten la transacción. Verificación de contraseña administrativa usa el thread pool. Las rutas de perfil y login eliminan commits duplicados y login no expone excepciones internas.
- JWT con sid valida sesión, propietario, vencimiento y ausencia de logout antes de admitir al usuario. Revocar una sesión ahora impide reutilizar ese token local. Tokens sin sid conservan compatibilidad con JWT Supabase y tokens históricos; la revocación local no invalida esos tokens externos.
- Búsqueda valida rangos geográficos y acota sugerencias a 1–50. La corrección inicial del parámetro se ajustó después de contrastar el modelo: LayerFeature.id es BIGINT, no UUID. El quinto lote utiliza enteros positivos y elimina el cast UUID.

Validación: 63 pruebas aprobadas con Python 3.13.12. Tres utilizan un Redis 5.0.14.1 real aislado, incluido el escenario de 30 peticiones concurrentes con límite cinco. La aplicación completa importó, generó OpenAPI con 66 rutas y respondió HTTP 200 en /health, usando configuración ficticia; no demuestra conectividad externa. Compilación de sintaxis aprobada.

Pendientes que requieren su propio lote: cuota diaria con reservas concurrentes (actualmente depende de logs posteriores a la respuesta), upsert atómico de estadísticas diarias con restricción única/migración, permisos por capa en búsqueda global, token administrativo basado en Admin frente a resolución de identidad basada en User, revocación de JWT externos y separación de módulos grandes de cartografía/IA/reportes. No se ejecutaron migraciones ni despliegues.

## Quinto lote: acceso público de búsqueda y archivos de capas

Las rutas de búsqueda, sugerencias y visualización resuelven identidad opcional. Para usuarios anónimos, todas las consultas restringen resultados a capas PUBLIC; usuarios autenticados conservan la política actual de listado de capas. El servicio recibe `public_only` explícitamente desde HTTP; sus consumidores internos conservan su contrato. Cuatro pruebas nuevas cubren propagación HTTP y ejecutan sugerencias/visualizaciones en SQLite en memoria para comprobar aislamiento de datos privados. El SQL geoespacial de PostgreSQL todavía requiere una integración PostGIS real.

La ruta de visualización usa IDs enteros positivos conforme a LayerFeature.id (BIGINT). Al contrastar migraciones se detectó que fecha_ubicado no existe. Se agregó last_viewed_at nullable al modelo y una migración nueva h8i9j0k1l2m3, hija del único head previo g7h8i9j0k1l2. Alembic conserva un solo head. El SQL de esta revisión se generó offline en docs/migrations/add-feature-last-viewed-at.sql, sin conectarse ni aplicar cambios.

Las cargas de capas también leen como máximo 50 MB más un byte de detección, procesan JSON/ZIP fuera del event loop, restauran el cursor y limpian el ZIP temporal incluso si falla GeoPandas. Carga y actualización traducen exceso de tamaño a HTTP 413. Cuatro pruebas nuevas cubren esos comportamientos.

Validación final: 71 pruebas aprobadas y sintaxis compilada. OpenAPI y /health se comprobaron con la aplicación completa y credenciales ficticias. Antes de desplegar, aplicar la nueva migración en el entorno destino y configurar Redis si existen API keys con RPM. No se aplicó la migración a bases reales. La privacidad corregida se limita a búsqueda: los endpoints de detalle, GeoJSON, propiedades y estadísticas de capas requieren una revisión propia de autorización. Siguen pendientes reservas de cuota diaria y actualización concurrente de estadísticas; no se presentan como resueltas.

## Sexto lote: lecturas públicas de capas

Se resolvió el pendiente de lectura anónima de capas. Categorías, árbol de categorías, propiedades, detalle de feature, valores de campos, estadísticas y GeoJSON propagan `public_only` a sus consultas. Sin identidad, se incluyen solo capas PUBLIC; con identidad se conserva la política existente. Los filtros se aplican en SQL, antes de obtener datos, incluyendo listas mixtas de IDs. El detalle privado o ausente responde 404; colecciones y agregados omiten las filas privadas. Esto no introduce aislamiento por propietario para usuarios autenticados ni cambia los permisos de escritura existentes.

El repositorio de features acepta IDs enteros y cadenas de dígitos; elimina el fallback UUID y la conversión truncada de float. Los fallos de base de datos ya no se silencian como feature ausente. Se agregaron seis pruebas, incluyendo siete rutas de lectura y verificación de los filtros ORM/SQL con sesiones simuladas.

Verificación final de este trabajo: **77 pruebas aprobadas**, compilación de app/tests/alembic y git diff --check sin errores. La aplicación generó OpenAPI con 66 rutas y /health respondió 200. Se verificó una única cabeza Alembic y se generó el SQL de la nueva revisión sin aplicarlo. Permanecen los pendientes de concurrencia diaria, integración PostgreSQL/PostGIS real, autenticación administrativa legacy y refactorización de módulos grandes. Los resultados de lotes anteriores se conservan como historial, no como estado final.

## Séptimo lote: reservas de cuota y estadísticas atómicas

La autenticación reserva cupo antes de admitir una petición. El repositorio bloquea la fila User con FOR UPDATE, vuelve a comprobar la cuota compartida entre sus API keys y persiste un log pendiente (status 102, quota_pending=true) antes de soltar el bloqueo. La comprobación inicial sigue siendo una optimización; la comprobación bajo bloqueo decide la admisión. Resolver la misma API key varias veces en una petición no duplica cupo ni RPM.

La ventana de 24 horas se cuenta desde la admisión. Se contabilizan resultados exitosos y pendientes; la finalización de errores libera cupo. Reservas abandonadas o no finalizadas por fallo de logging conservan cupo hasta salir de la ventana. El middleware ASGI registra el resultado antes de enviar cabeceras y espera como máximo cinco segundos; conserva la respuesta del negocio si ese registro falla. Evita tareas sin seguimiento y no introduce buffers adicionales para streaming. En respuestas transmitidas por partes, el estado registrado es el de las cabeceras.

Finalizar una reserva actualiza condicionalmente su log pendiente, luego los totales y las estadísticas, en una transacción. Una finalización repetida no vuelve a sumar. Las estadísticas usan INSERT ON CONFLICT y sumas SQL bajo una restricción única por API key/fecha, con fecha UTC de admisión. El diseño se contrastó con la documentación de bloqueos y ON CONFLICT de PostgreSQL: https://www.postgresql.org/docs/current/explicit-locking.html y https://www.postgresql.org/docs/current/sql-insert.html.

La revisión i9j0k1l2m3n4, hija de h8i9j0k1l2m3, agrega quota_pending y la restricción única. Se detiene ante duplicados históricos sin borrarlos ni fusionarlos; bloquea la tabla de estadísticas durante esa validación. SQL offline disponible en docs/migrations/add-atomic-api-key-usage.sql. No se aplicó a una base real. Antes de desplegar deben aplicarse las revisiones pendientes y actualizar todos los workers; mezclar versiones con/sin reservas no garantiza la misma política de admisión.

Se agregaron catorce pruebas. La suite completa pasa con **91 pruebas**. Una prueba ejecuta 30 upserts concurrentes en SQLite y conserva una fila con 30 peticiones y 60 tokens. Las pruebas de reserva inspeccionan SQL PostgreSQL y usan sesiones simuladas: aún falta validar el bloqueo y las carreras en PostgreSQL real. Continúan pendientes autenticación administrativa legacy, pruebas externas/PostGIS, runtime Python 3.12 y refactorización de los módulos grandes. Las garantías de PostgreSQL se basan en la implementación y el contrato SQL; no se presentan como una prueba de carga de producción.
