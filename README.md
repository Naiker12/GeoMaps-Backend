<p align="center">
  <img src="docs/assets/geomaps-icon.svg" alt="Icono oficial de GeoMaps" width="112" height="112" />
</p>

<h1 align="center">GeoMaps Backend</h1>

<p align="center">API del visor geográfico y del panel administrativo<br />FastAPI · PostgreSQL/PostGIS · Supabase · Redis · IA geográfica</p>

Backend de GeoMaps construido con FastAPI, SQLAlchemy Async, PostgreSQL/PostGIS, Supabase y Google Gemini. Expone la API que alimenta el visor geoespacial, el panel administrativo, capas GIS, busqueda, descargas, API keys, usuarios, analitica e IA.

Este README documenta la arquitectura real del backend, sus servicios, librerias, variables de entorno, comandos, rutas y responsabilidades.

La aplicación declara la versión **2.0.0**. El icono se reutiliza del frontend oficial y se conserva dentro del repositorio para evitar dependencias externas al mostrarlo en GitHub. Este documento diferencia funcionalidades activas, código histórico y validaciones pendientes.

## Tabla De Contenido

- [Funciones principales](#funciones-principales)
- [Stack tecnico](#stack-tecnico)
- [Arquitectura](#arquitectura)
- [Estructura de carpetas](#estructura-de-carpetas)
- [Servicios del backend](#servicios-del-backend)
- [Modelos principales](#modelos-principales)
- [Referencia API](#referencia-api)
- [Variables de entorno](#variables-de-entorno)
- [Instalacion y ejecucion](#instalacion-y-ejecucion)
- [Base de datos y migraciones](#base-de-datos-y-migraciones)
- [Autenticacion y seguridad](#autenticacion-y-seguridad)
- [IA](#ia)
- [Observabilidad](#observabilidad)
- [Buenas practicas](#buenas-practicas)
- [Relacion con el frontend](#relacion-con-el-frontend)
- [IA geográfica y resultados](#ia-geográfica-y-resultados)
- [Cuotas y concurrencia](#cuotas-y-concurrencia)
- [Preparación del despliegue](#preparación-del-despliegue)
- [Pruebas y alcance de validación](#pruebas-y-alcance-de-validación)
- [Solución de problemas](#solución-de-problemas)
- [Ramas de trabajo](#ramas-de-trabajo)
- [Documentación complementaria](#documentación-complementaria)

## Funciones Principales

| Modulo | Funcion |
| --- | --- |
| API REST | Expone rutas versionadas bajo `/api/v1`. |
| Autenticacion | Valida JWT de Supabase, sincroniza usuarios y protege rutas privadas. |
| Usuarios | Gestiona perfiles, roles, sesiones y operaciones administrativas. |
| Capas GIS | Carga, almacena y consulta capas geograficas con features y geometria PostGIS. |
| Busqueda | Busca features GIS por texto o coordenadas. |
| Descargas | Administra recursos descargables, archivos, metadatos y publicacion. |
| API Keys | Emite, revoca, audita y monitorea llaves de API. |
| Administracion | Dashboards, analitica, monitoreo de IA y gestion global. |
| IA | Chat, streaming, historial, sugerencias, uso, herramientas y proveedor Gemini. |
| Storage | Integra Supabase Storage para archivos publicos o administrativos. |
| Auditoria | Registra tiempos de respuesta, uso de API keys y actividad del sistema. |

## Stack Tecnico

| Libreria / Herramienta | Version | Uso en el proyecto |
| --- | --- | --- |
| FastAPI | `0.115.6` | Framework principal ASGI para API REST. |
| Uvicorn | `0.34.0` | Servidor ASGI local/produccion. |
| SQLAlchemy | `2.0.36` | ORM async, modelos y consultas. |
| GeoAlchemy2 | `0.17.0` | Tipos y funciones geoespaciales para PostGIS. |
| Psycopg | `3.2.10` | Driver PostgreSQL async/binario. |
| Alembic | `1.14.0` | Migraciones de base de datos. |
| Redis, cliente Python | `5.2.1` | Caché de historial IA, límites RPM y estado de reportes. |
| HTTPX | `0.28.1` | Cliente HTTP para JWKS de Supabase y llamadas externas. |
| Pandas | `2.2.3` | Procesamiento tabular de datos. |
| NumPy | `2.2.0` | Calculo numerico. |
| Shapely | `2.0.6` | Manipulacion de geometria. |
| PyProj | `3.7.1` | Transformaciones de coordenadas. |
| GeoPandas | `1.0.1` | Lectura/procesamiento de archivos geoespaciales. |
| Fiona | `1.10.1` | Lectura de formatos GIS como Shapefile. |
| python-multipart | `0.0.19` | Uploads `multipart/form-data`. |
| python-dotenv | `1.0.1` | Carga de variables desde `.env`. |
| pydantic-settings | `2.7.0` | Configuracion tipada del entorno. |
| Supabase | `2.11.0` | Auth, storage y operaciones con Supabase. |
| Authlib | `1.3.2` | Manejo de JWT/JWK y soporte criptografico. |
| pwdlib[argon2] | `0.2.1` | Hash/verificacion de contrasenas cuando aplica. |
| email-validator | `>=2.0.0` | Validacion de correos en schemas Pydantic. |
| greenlet | sin pin | Soporte requerido por SQLAlchemy async. |
| google-genai | `>=1.0.0` | Cliente oficial para Google Gemini. |
| Matplotlib | `>=3.8.0` | Gráficas utilizadas en reportes. |
| Typst | `0.14.8` | Render de documentos PDF. |

Las versiones describen `requirements.txt`; no indican que sean las últimas publicadas. El archivo exige wheels binarios con `--only-binary=:all:`. La configuración de despliegue fija Python 3.12.8.

## Arquitectura

El backend usa una arquitectura modular por capas:

| Capa | Ubicacion | Responsabilidad |
| --- | --- | --- |
| Entrada ASGI | `app/main.py` | Crea FastAPI, configura CORS, middleware, excepciones, lifespan y rutas. |
| Configuracion | `app/core/config.py` | Centraliza variables de entorno con Pydantic Settings. |
| Seguridad | `app/core/security` | JWT local, JWT Supabase, dependencias de usuario y roles. |
| API | `app/api` | Routers HTTP y dependencias de FastAPI. |
| Schemas | `app/schemas` | Contratos Pydantic de request/response. |
| Modelos DB | `app/db/models` | Tablas SQLAlchemy y tipos PostGIS. |
| Sesion DB | `app/db/session.py` | Engine async y `AsyncSession`. |
| Servicios | `app/services` | Reglas de negocio: capas, descargas, busqueda, IA, analitica. |
| Repositorios | `app/repositories` | Acceso a datos y consultas reutilizables. |
| Infraestructura | `app/infrastructure` | Clientes externos como Gemini y repositorios concretos. |
| Dominio | `app/domain` | Modelos y servicios de dominio para permisos/roles. |
| Migraciones | `alembic` | Versionado de cambios de base de datos. |

## Estructura De Carpetas

```txt
app/
  api/
    routes/               Rutas legacy o compartidas.
    v1/                   API versionada principal.
      admin/              Rutas administrativas.
      endpoints/          Rutas especializadas como IA.
  application/            Servicios de aplicacion por dominio.
  core/                   Configuracion, logging, excepciones y seguridad.
  db/
    models/               Modelos SQLAlchemy.
    session.py            Engine y sesiones async.
  domain/                 Modelos y reglas de dominio.
  infrastructure/         Clientes externos e implementaciones concretas.
  repositories/           Repositorios de datos.
  schemas/                Schemas Pydantic.
  services/               Logica de negocio.
  utils/                  Utilidades compartidas.
alembic/                  Migraciones.
docs/                     Documentacion complementaria.
```

## Servicios del backend

Los routers coordinan entrada HTTP y dependencias; los servicios aplican reglas de negocio y los repositorios reutilizan el acceso a datos. Para ampliar una función, seguir los imports del módulo activo antes de crear una implementación paralela.

| Servicio | Responsabilidad |
| --- | --- |
| layers / spatial / geospatial | Archivos GIS, features, validación y consultas espaciales |
| search / cartografia | Búsqueda y recursos cartográficos |
| ia | Contexto, herramientas, historial y consumo de modelos |
| api_keys | Gestión de llaves y finalización de consumo |
| downloads / storage | Catálogo y archivos externos |
| report / export | Construcción y render de reportes |
| analytics / support | Estadísticas administrativas y atención de solicitudes |

El código histórico de proyectos permanece únicamente donde preserva compatibilidad de modelos y migraciones. La presencia de un directorio de servicio no garantiza que tenga un router público registrado; consultar app/main.py y OpenAPI.

## Modelos Principales

| Modelo | Tabla | Funcion |
| --- | --- | --- |
| `User` | `users` | Perfil interno, rol, estado, datos personales y relacion con Supabase. |
| `UserSession` | `user_sessions` | Sesiones de usuarios/admins, IP, user agent y expiracion. |
| `Admin` | `admins` | Administradores internos cuando aplica. |
| Modelos históricos de proyectos | `projects` y tablas asociadas | Conservados para preservar datos y migraciones; sin API activa de proyectos. |
| `Layer` | `layers` | Metadatos de capa GIS, visibilidad, estilo, archivo y configuraciones. |
| `LayerFeature` | `layer_features` | Entidades individuales con propiedades JSONB y geometria PostGIS. |
| `DownloadResource` | `download_resources` | Recursos descargables, archivo, categoria, tags y publicacion. |
| `APIKey` | `api_keys` | Llaves de API, rol, visibilidad, limites, estado y hash. |
| `APIKeyUsageLog` | `api_key_usage_logs` | Auditoria de uso por endpoint, metodo, estado, latencia e IP. |
| `APIKeyDailyStats` | `api_key_daily_stats` | Agregados diarios por llave. |
| `ActivityLog` | `activity_logs` | Eventos de actividad del sistema. |

## Referencia API

El backend expone una API versionada bajo `/api/v1`. La fuente de verdad para rutas, parámetros, permisos y schemas es la documentación interactiva generada por FastAPI:

```txt
http://localhost:8000/api/v1/docs
http://localhost:8000/api/v1/redoc
http://localhost:8000/api/v1/openapi.json
```

El estado basico del servicio se valida con:

```txt
GET /health
```

`/health` confirma que responde el proceso y devuelve su versión; no verifica automáticamente la salud de PostgreSQL, Redis, Supabase ni los proveedores de IA.

Para documentar nuevas rutas, se recomienda usar `response_model`, descripciones claras en los routers y schemas Pydantic; de esa forma Swagger/OpenAPI permanece actualizado sin duplicar tablas en este archivo.

## Variables De Entorno

Crear `.env` en la raiz del backend.

```env
DATABASE_URL=postgresql://user:password@host:5432/database
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_KEY=your-service-key
SUPABASE_JWT_SECRET=your-supabase-jwt-secret
JWT_SECRET=your-local-jwt-secret
SECRET_KEY=your-local-secret-key
GOOGLE_API=your-google-gemini-api-key
FRONTEND_URL=http://localhost:5173
BACKEND_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

| Variable | Obligatoria | Descripcion |
| --- | --- | --- |
| `DATABASE_URL` | Si | Conexion PostgreSQL. El codigo convierte `postgres://`/`postgresql://` a `postgresql+psycopg://` cuando aplica. En Render con Supabase usa el pooler IPv4, no `db.<project>.supabase.co`. |
| `SUPABASE_URL` | Si | URL del proyecto Supabase. |
| `SUPABASE_ANON_KEY` | Si | Llave anonima para operaciones de auth. |
| `SUPABASE_SERVICE_KEY` | Recomendada | Llave service role para storage/operaciones administrativas. |
| `SUPABASE_JWT_SECRET` | Si | Secreto usado para validar tokens Supabase. |
| `SECRET_KEY` | Para sesiones locales | Configurar explícitamente un secreto local independiente; no confundirlo con SUPABASE_JWT_SECRET. |
| `JWT_SECRET` | Legacy | Campo de compatibilidad; comprobar Settings antes de depender de él como sustituto de SECRET_KEY. |
| `GOOGLE_API` | Si usa IA | API key de Google Gemini. |
| `FRONTEND_URL` | Recomendada | URL del frontend para CORS y callbacks. |
| `BACKEND_CORS_ORIGINS` | Recomendada | Lista de origenes permitidos separados por coma o JSON list. |
| `REDIS_URL` | Según función | Obligatoria para reportes y API keys con límite RPM; default redis://localhost:6379. |
| `SUPABASE_JWT_ISSUER` | Opcional | Por defecto deriva de SUPABASE_URL/auth/v1. |
| `REDIS_TTL_HISTORY` / `REDIS_TTL_SUMMARY` | Opcional | Defaults 3600 y 86400 segundos. |
| `IA_USAGE_LIMIT` / `IA_USAGE_WINDOW_HOURS` | Opcional | Defaults 15 y 4; separados de las cuotas API key. |
| `DEBUG` | Opcional | Default false. |

La plantilla [.env.example](.env.example) permite empezar sin publicar secretos. Copiarla a `.env` y completar sus valores; añadir SECRET_KEY explícitamente. La lista completa de opciones está en [Settings](app/core/config.py).

Correo de soporte utiliza SUPPORT_EMAIL_ENABLED, SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_EMAIL, SMTP_FROM_NAME y SUPPORT_REPLY_TO_EMAIL. Está deshabilitado por defecto. Registrar una solicitud no garantiza que se haya enviado correo.

### Supabase En Render

Si la conexión directa de Supabase no es alcanzable desde la red del despliegue y aparece `Network is unreachable`, revisar la resolución de direcciones y la connection string del proyecto antes de cambiar la aplicación.

En Supabase Dashboard -> Project Settings -> Database -> Connection string, copia una URL de pooler:

- Session pooler para este backend persistente: `postgres://postgres.<project-ref>:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:5432/postgres`
- Transaction pooler si prefieres puerto `6543`: `postgres://postgres.<project-ref>:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres`

Pega esa URL como `DATABASE_URL` en Render. El backend desactiva prepared statements automaticamente cuando detecta el transaction pooler `:6543`.

## Instalacion Y Ejecucion

Requisitos recomendados:

- Python 3.12.8, como declara la configuración de despliegue.
- PostgreSQL con extension PostGIS.
- Redis para reportes y API keys con RPM; historial IA tiene caché con fallback a DB.
- Proyecto Supabase configurado.

Windows PowerShell:

```powershell
git clone https://github.com/Naiker12/GeoMaps-Backend.git
cd GeoMaps-Backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
# Completar .env y preparar la base antes de arrancar.
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Linux/macOS:

```bash
cd GeoMaps-Backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Completar .env y preparar la base antes de arrancar.
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

URLs utiles:

| URL | Uso |
| --- | --- |
| `http://localhost:8000/health` | Health check. |
| `http://localhost:8000/api/v1/docs` | Swagger/OpenAPI. |
| `http://localhost:8000/api/v1/redoc` | ReDoc. |

## Base De Datos Y Migraciones

El proyecto usa SQLAlchemy async y Alembic.

Comandos comunes:

```bash
alembic current
alembic heads
alembic history
# Tras revisar respaldo, revisión destino y datos:
alembic upgrade head
alembic revision --autogenerate -m "descripcion_del_cambio"
```

Consideraciones:

- La base de datos debe tener PostGIS habilitado.
- Las geometrias principales usan SRID `4326`.
- Las entidades GIS usan `JSONB` para propiedades flexibles.
- Revisar índices espaciales y planes reales de las consultas que se usan en producción.
- No ejecutar init_db.sql a ciegas sobre una base existente; conserva definiciones históricas y no sustituye Alembic.

## Autenticacion Y Seguridad

El backend soporta dos mecanismos principales:

| Mecanismo | Uso |
| --- | --- |
| JWT Supabase | Autenticacion del frontend, perfil de usuario y rutas privadas. |
| API Key | Acceso programatico y auditoria de consumo por endpoint. |

Flujo general:

1. El frontend inicia sesion con Supabase.
2. El frontend envia `Authorization: Bearer <access_token>`.
3. El backend valida token con dependencias de seguridad.
4. POST /api/v1/auth/login/supabase sincroniza el perfil y genera sesión local con cookie HttpOnly.
5. Las rutas administrativas verifican rol antes de permitir operaciones.
6. Las API keys se envian con `X-API-Key` o `api_key`.
7. El middleware registra uso exitoso o intento fallido.

Crear un usuario en Supabase Authentication **no concede acceso administrativo**. Los perfiles nuevos reciben USER; los privilegios se asignan explícitamente sobre el perfil local mediante un procedimiento autorizado. No se toman roles administrativos de metadatos de registro.

User.id y User.supabase_id son identidades distintas. El adaptador interno login_admin exige User activo con el mismo correo y rol ADMIN/SUPER_ADMIN; el flag histórico Admin.is_superadmin no reemplaza ese rol ni publica un endpoint adicional.

Los JWT Supabase admiten HS256 y ES256/RS256 con JWKS. Se verifican claims, expiración, issuer y audience. El secreto HS256 es texto literal, aunque parezca Base64. JWKS conserva caché durante diez minutos y limita recargas por kid desconocido a una por minuto.

## IA

La capa IA se concentra en `app/services/ia` e `app/infrastructure/ia_llm_client.py`.

Responsabilidades:

- Construir prompts con contexto de GeoMaps.
- Enviar mensajes a Google Gemini usando `google-genai`.
- Soportar respuesta normal y streaming.
- Persistir conversaciones en DB y acelerar historial/resumen mediante Redis.
- Exponer modelos, sugerencias, conversaciones y uso.
- Registrar informacion de monitoreo para administracion.
- Ejecutar herramientas que el frontend puede traducir en acciones de mapa.

Variable requerida para proveedor Gemini:

```env
GOOGLE_API=your-google-gemini-api-key
```

## Observabilidad

El backend incluye:

- Middleware que mide tiempo de respuesta y agrega `X-Process-Time`.
- Registro de uso de API keys exitoso o fallido.
- Logs configurados desde `app/core/logging.py`.
- Health check en `/health`.
- Endpoints administrativos de analitica e IA.

## Buenas Practicas

- Mantener routers delgados: la logica debe vivir en servicios.
- Usar schemas Pydantic para requests/responses.
- Usar repositorios para consultas repetidas o complejas.
- No exponer `SUPABASE_SERVICE_KEY` al frontend.
- Validar roles en rutas administrativas.
- Ejecutar migraciones antes de levantar entornos nuevos.
- Mantener los tipos del frontend sincronizados con los schemas del backend.
- Documentar cualquier endpoint nuevo en este README y en OpenAPI mediante `response_model`.

## Relacion Con El Frontend

El frontend espera este backend bajo:

```txt
http://localhost:8000/api/v1
```

CORS debe permitir al menos:

```txt
http://localhost:5173
http://127.0.0.1:5173
```

Los contratos consumidos por el frontend se reflejan especialmente en:

- `src/services/*` del frontend.
- `src/core/types/*` del frontend.
- `app/schemas/*` del backend.
- `app/api/v1/*` y `app/api/routes/*` del backend.

## Retiro del módulo de proyectos

La funcionalidad de proyectos fue retirada del admin, del visor público y de la API. Los datos, las tablas, las migraciones y los archivos almacenados se conservan. Los modelos de proyectos del backend son históricos y permanecen registrados para evitar eliminaciones de tablas en futuras migraciones. Consulta `docs/project-module-removal.md` y el inventario `docs/removed-project-files.txt`.

## IA geográfica y resultados

El modelo interpreta una pregunta y selecciona herramientas. Los conteos, intersecciones y superficies los calcula PostGIS; no deben inventarse en el texto del modelo. El frontend interpreta las acciones y gráficos estructurados que devuelve el backend.

El contexto prioriza la zona de conversación, después la extensión de conversación y finalmente el viewport. Extensiones Web Mercator compatibles se transforman a EPSG:4326; sistemas desconocidos o rangos inválidos se rechazan antes del chat o las cabeceras SSE.

### Herramienta de análisis

`analizar_capa_geografica` resuelve una capa, mide su distribución geométrica y devuelve métricas con procedencia.

| Entrada | Alcance |
| --- | --- |
| layer_name y layer_id opcional | Selección por nombre/ID; ambigüedad devuelve candidatos |
| bbox | Extensión rectangular e intersección exacta |
| zone_geometry | Polygon/MultiPolygon GeoJSON válido en EPSG:4326 |
| coordinates y radius_m | Proximidad en metros, radio de 1 a 50.000 |
| scope=entire_layer | Toda la capa sin filtros espaciales heredados |

Un polígono seleccionado sustituye el viewport para esta herramienta. Una búsqueda por radio mantiene su propio centro. El orden de coordenadas es longitud, latitud. Una extensión rectangular no representa el límite administrativo de un barrio.

Ejemplo de cuerpo para POST /api/v1/ia/chat, con el nombre de una capa disponible:

```json
{
  "message": "Cuenta los parques en el área visible y muestra su distribución geométrica",
  "context_mapa": {
    "extent": [-75.6, 6.1, -75.5, 6.3]
  }
}
```

### Contrato de presentación

| Campo | Propósito |
| --- | --- |
| message | Hallazgo, fuente/alcance y limitación relevante |
| conversation_id | Continuidad del historial |
| map_actions | Acciones visuales que interpreta el visor |
| analytics_data | Gráfico compatible; conserva el último gráfico |
| analysis_results | Metadatos de todos los análisis realizados |
| suggestions | Seguimientos sugeridos |
| tokens_input, tokens_output y cost | Datos de consumo |

En streaming, el evento done incluye los resultados estructurados. El flujo del agente comprueba propiedad de la conversación antes de cargar historial y resumen.

Los conteos incluyen geometrías válidas, no nulas, SRID 4326 y dentro de rango. La suma de áreas se calcula en m² sobre geography, pero suma polígonos completos: no recorta a la zona ni elimina solapamientos. **No es porcentaje de cobertura**. Los filtros de atributos del contexto no se aplican automáticamente en esta herramienta; no presentar la métrica como un subconjunto filtrado por atributos.

### Configuración de proveedores

El workspace también contiene una ampliación en desarrollo para conexiones de proveedores y modelos: `app/services/ia/provider_connections.py`. Incluye configuración cifrada y adaptadores HTTP. Su publicación y migración deben revisarse con ese lote; no asumir que la versión remota ya cuenta con él. El funcionamiento de Gemini depende de GOOGLE_API y de los modelos activos de la base.

## Cuotas y concurrencia

Las API keys tienen controles distintos de los límites de uso IA. Preferir X-API-Key al parámetro api_key para evitar incluir credenciales en enlaces y navegación.

| Control | Comportamiento |
| --- | --- |
| RPM por llave | Ventana Redis de 60 segundos desde primera admisión; Lua atómico |
| rate_limit_rpm=null | No usa el control RPM |
| RPM excedido | HTTP 429 con Retry-After |
| Redis inaccesible para llave limitada | HTTP 503 |
| Cuota compartida por usuario | DAILY_API_KEY_LIMIT=10; ventana móvil de 24 horas |

La admisión reserva cupo mediante bloqueo de la fila del usuario y cuenta éxitos o reservas pendientes. Varias llaves de un usuario comparten cuota. Una finalización fallida libera cupo; una reserva interrumpida sigue contando hasta salir de la ventana.

La finalización es idempotente y actualiza log, totales y agregados en transacción. El middleware espera hasta cinco segundos antes de enviar cabeceras; en streaming registra el estado de cabeceras, no cada fragmento del cuerpo. Actualizar todos los workers para compartir la misma garantía de admisión.

## Archivos, transacciones y reportes

El servicio compartido de Storage limita cargas a **50 MiB** y mueve llamadas síncronas del SDK a hilos. Los metadatos incluyen bucket, ruta, tamaño, extensión y MIME.

| Categoría | Bucket mapeado |
| --- | --- |
| layers / capas | Capas |
| profiles / avatars | profiles |
| downloads | Download |
| resources | resources |
| images | Imagen |
| models | Imagen3d; compatibilidad histórica |

Los buckets y policies deben prepararse en Supabase. Una URL almacenada no acredita que el cliente tenga acceso. El catálogo de descarga pública exige publicación y visibilidad pública; modificar o borrar recursos requiere propiedad o administración activa.

El reemplazo de capa carga el archivo nuevo antes de retirar features, bloquea la fila y confirma metadatos/geometrías juntos. Ante fallo DB se revierte y procura limpiar el archivo nuevo. El archivo anterior se limpia después del commit. DB y Storage no tienen transacción distribuida: una limpieza fallida puede dejar archivos huérfanos.

POST /api/v1/reports/generate inicia un trabajo de fondo con su propia sesión DB. Estado y descarga requieren propietario autenticado. El estado tiene TTL Redis de una hora; un estado ausente, vencido o ajeno devuelve 404. El render PDF se ejecuta fuera del event loop.

El trabajo depende del worker y no constituye una cola durable. Revisar reinicios, persistencia del filesystem y limpieza de PDFs antes de asumir que un reporte seguirá disponible. Un fallo Redis al inicializar el reporte devuelve 503.

## Preparación del despliegue

[render.yaml](render.yaml) declara Python 3.12.8, instalación de requirements y Uvicorn con el puerto del entorno. El comando de arranque no aplica migraciones.

1. Respaldar DB y comprobar revisión Alembic del destino.
2. Revisar migraciones, duplicados de estadísticas y compatibilidad de schemas.
3. Aplicar revisiones mediante el proceso controlado del entorno.
4. Configurar secretos, Redis, buckets/policies, CORS y modelos activos.
5. Probar login, cuotas, lectura/escritura GIS, cargas, chat y reportes con servicios reales.
6. Comprobar logs, latencias y comportamiento al reiniciar workers.

| Revisión reciente | Cambio | Condición |
| --- | --- | --- |
| h8i9j0k1l2m3 | layer_features.last_viewed_at | Depende de g7h8i9j0k1l2 |
| i9j0k1l2m3n4 | quota_pending y unicidad llave/fecha de estadísticas | Depende de h8i9j0k1l2m3; se detiene con duplicados |

La revisión de estadísticas no borra ni fusiona duplicados automáticamente. El SQL offline de [docs/migrations](docs/migrations) permite revisar operaciones; no sustituye Alembic sobre una revisión destino diferente. Para cambios posteriores, consultar también las migraciones en desarrollo y su documentación específica.

## Pruebas y alcance de validación

```bash
python -m unittest discover -s tests -v
python -m compileall -q app tests
git diff --check
python -m alembic heads
```

Para un módulo concreto:

```bash
python -m unittest discover -s tests -p test_ai_geography.py -v
python -m unittest discover -s tests -p test_layer_transactions.py -v
```

La revisión del 12 de octubre de 2026 aprobó 151 pruebas, OpenAPI y /health 200 con Python 3.13.12 local. Es una instantánea de validación, no un badge automático de CI. Los cambios de desarrollo posteriores requieren sus propias comprobaciones.

| Área | Evidencia | Límite |
| --- | --- | --- |
| JWT y permisos | Tokens firmados de prueba, dependencias FastAPI | Sin Supabase real |
| Cuotas/RPM | Redis aislado, mocks y upsert SQLite concurrente | Sin bloqueo real PostgreSQL |
| Capas/archivos | Propiedad, rollback y compensación | Storage y DB simulados |
| GIS | Parámetros SQL, bbox, polígonos y pyproj real | Sin métricas ejecutadas en PostGIS |
| IA | Alcance y metadatos de respuesta | Sin evaluación de modelo real |
| Reportes/OGC | Propiedad, sesiones y límites de streaming | Sin PDF real ni servidor OGC externo |

El entorno ficticio de tests no escribe .env ni aplica migraciones. Las integraciones Redis se omiten explícitamente si no se encuentra redis-server. Consultar [tests/README.md](tests/README.md) para el detalle.

## Solución de problemas

| Síntoma | Comprobación |
| --- | --- |
| Settings falla al importar | Variables requeridas y .env en raíz |
| SECRET_KEY ausente | Configurar secreto local explícito |
| 401 con sesión | Expiración, issuer/audience, revocación y usuario activo |
| 403 de administración | Rol local; cuenta Supabase no equivale a ADMIN |
| Columna last_viewed_at/quota_pending ausente | Revisión Alembic y migraciones |
| Migración detenida | Duplicados llave/fecha; revisar datos |
| 503 de cuotas | Conectividad Redis y configuración RPM |
| 429 | Cuota compartida y ventana RPM; respetar Retry-After |
| Cookie o CORS | Origen, credentials, hostname y HTTPS |
| Upload rechazado | Tamaño, bucket, clave backend y policies |
| Chat sin modelo | Modelos activos y configuración del proveedor |
| Área distinta de cobertura | Alcance, polígonos completos y solapamientos |
| Reporte ausente | TTL Redis, worker y PDF local |

## Ramas de trabajo

Las ramas usan feature/, sin prefijo codex. Seguridad, Mapa, IA, Descargas, Proyectos y Documentacion organizaron los cambios integrados. Se prepararon ramas adicionales para Autenticacion, Usuarios, Capas, Busqueda, ApiKeys, Cartografia, OGC, Reportes, Almacenamiento, Analitica, Soporte, Notificaciones, Portal y Administracion.

Una rama preparada sin commits propios no representa una funcionalidad nueva. Sincronizar con main antes de desarrollar; validar contratos, permisos, migraciones y pruebas relevantes antes de fusionar. No añadir secretos ni archivos temporales a los commits.

## Documentación complementaria

| Documento | Contenido |
| --- | --- |
| [Preparación del despliegue](docs/preparacion-despliegue-refactor.md) | Migraciones, Redis y operación |
| [Diseño de IA geográfica](docs/ia-geografica-diseno-y-validacion.md) | Alcance, unidades y limitaciones |
| [Revisión del backend](docs/revision-backend-2026-10-12.md) | Hallazgos y validaciones |
| [Plan de refactorización](docs/revision-y-plan-refactorizacion.md) | Inventario y prioridades |
| [Retiro de proyectos](docs/project-module-removal.md) | Código retirado y datos preservados |
| [Organización de ramas](docs/ramas-integracion-2026-10-12.md) | Dependencias de integración |
| [Pruebas](tests/README.md) | Ejecución y alcance por módulo |
| [Configuración](app/core/config.py) | Opciones reconocidas |
| [Dependencias](requirements.txt) | Versiones declaradas |

## Inventario de rutas

La siguiente instantánea se genera del OpenAPI local. Consultar Swagger para cuerpos y respuestas. Una ruta presente no implica acceso público; sus dependencias determinan la autenticación y los permisos.

| Método | Ruta | Operación |
| --- | --- | --- |
| `GET` | `/api/v1/admin/analytics/charts` | Get Analytics Charts |
| `GET` | `/api/v1/admin/analytics/summary` | Get Analytics Summary |
| `GET` | `/api/v1/admin/analytics/usage` | Get System Usage |
| `GET` | `/api/v1/admin/api-keys/` | List Admin Api Keys |
| `POST` | `/api/v1/admin/api-keys/` | Admin Create Api Key |
| `PUT` | `/api/v1/admin/api-keys/settings/ip-whitelist` | Update Global Ip Whitelist |
| `POST` | `/api/v1/admin/api-keys/settings/pause` | Toggle Traffic Pause |
| `PATCH` | `/api/v1/admin/api-keys/settings/rate-limit` | Update Global Rate Limit |
| `GET` | `/api/v1/admin/api-keys/stats/overview` | Get Admin Stats Overview |
| `DELETE` | `/api/v1/admin/api-keys/{key_id}` | Admin Delete Api Key |
| `PATCH` | `/api/v1/admin/api-keys/{key_id}/revoke` | Admin Revoke Api Key |
| `GET` | `/api/v1/admin/ia/audit-logs` | Get Ia Audit Logs |
| `DELETE` | `/api/v1/admin/ia/audit-logs/clear` | Clear All Ia Data |
| `GET` | `/api/v1/admin/ia/audit-logs/user/{user_id}` | Get User Audit Detail |
| `GET` | `/api/v1/admin/ia/audit-logs/{log_id}/details` | Get Audit Log Details |
| `GET` | `/api/v1/admin/ia/models` | List All Models |
| `POST` | `/api/v1/admin/ia/models` | Create Model Config |
| `PATCH` | `/api/v1/admin/ia/models/{model_uuid}` | Update Model Config |
| `DELETE` | `/api/v1/admin/ia/models/{model_uuid}` | Delete Model Config |
| `GET` | `/api/v1/admin/ia/stats` | Get Ia Stats |
| `GET` | `/api/v1/admin/support/` | List Support Requests |
| `GET` | `/api/v1/admin/support/{request_id}` | Get Support Request |
| `PATCH` | `/api/v1/admin/support/{request_id}` | Update Support Request |
| `DELETE` | `/api/v1/admin/support/{request_id}` | Delete Support Request |
| `POST` | `/api/v1/admin/support/{request_id}/reply` | Reply Support Request |
| `GET` | `/api/v1/admin/users/` | List Admin Users |
| `POST` | `/api/v1/admin/users/` | Create User |
| `GET` | `/api/v1/admin/users/me` | Get My Profile |
| `PATCH` | `/api/v1/admin/users/me` | Update My Profile |
| `PATCH` | `/api/v1/admin/users/{user_id}` | Update User |
| `DELETE` | `/api/v1/admin/users/{user_id}` | Delete User |
| `POST` | `/api/v1/auth/login/supabase` | Login Supabase |
| `POST` | `/api/v1/auth/logout` | Logout |
| `GET` | `/api/v1/auth/me` | Get My Profile |
| `PATCH` | `/api/v1/auth/me` | Update My Profile |
| `POST` | `/api/v1/auth/me/avatar` | Upload Avatar |
| `GET` | `/api/v1/auth/sessions` | Get My Sessions |
| `DELETE` | `/api/v1/auth/sessions/{session_id}` | Revoke Session |
| `POST` | `/api/v1/cartografia/generate` | Generate Cartografia |
| `POST` | `/api/v1/ia/chat` | Chat With Ia |
| `POST` | `/api/v1/ia/chat/stream` | Chat With Ia Stream |
| `GET` | `/api/v1/ia/conversations` | Get Chat History |
| `DELETE` | `/api/v1/ia/conversations` | Delete Conversations |
| `DELETE` | `/api/v1/ia/conversations/{conversation_id}` | Delete Conversation |
| `GET` | `/api/v1/ia/conversations/{conversation_id}/messages` | Get Conversation Messages |
| `GET` | `/api/v1/ia/models` | Get Available Models |
| `GET` | `/api/v1/ia/suggestions` | Get Ia Suggestions |
| `POST` | `/api/v1/ia/transcribe` | Transcribe Audio |
| `GET` | `/api/v1/ia/usage` | Get Ia Usage |
| `GET` | `/api/v1/keys/` | List Api Keys |
| `POST` | `/api/v1/keys/` | Create Api Key |
| `GET` | `/api/v1/keys/stats` | Get My Stats |
| `DELETE` | `/api/v1/keys/{key_id}` | Delete Api Key |
| `PATCH` | `/api/v1/keys/{key_id}/revoke` | Revoke Api Key |
| `POST` | `/api/v1/layers/` | Upload Layer |
| `GET` | `/api/v1/layers/` | List Layers |
| `GET` | `/api/v1/layers/categories` | Get Categories |
| `GET` | `/api/v1/layers/categories/tree` | Get Categories Tree |
| `GET` | `/api/v1/layers/features/properties` | Get Layers Features Properties |
| `GET` | `/api/v1/layers/features/{feature_id}` | Get Feature Detail |
| `PATCH` | `/api/v1/layers/{layer_id}` | Update Layer |
| `DELETE` | `/api/v1/layers/{layer_id}` | Delete Layer |
| `GET` | `/api/v1/layers/{layer_id}/features` | Get Layer Geojson |
| `GET` | `/api/v1/layers/{layer_id}/field-stats` | Get Field Stats |
| `GET` | `/api/v1/layers/{layer_id}/field-values` | Get Field Values |
| `GET` | `/api/v1/ogc/proxy` | Proxy Ogc Request |
| `GET` | `/api/v1/reports/download/{report_id}` | Download Report Pdf |
| `POST` | `/api/v1/reports/generate` | Generate Report |
| `GET` | `/api/v1/reports/status/{report_id}` | Get Report Status |
| `GET` | `/api/v1/reports/types` | Get Report Types |
| `GET` | `/api/v1/resources/` | List Admin Downloads |
| `POST` | `/api/v1/resources/` | Create Download |
| `GET` | `/api/v1/resources/public` | List Public Downloads |
| `DELETE` | `/api/v1/resources/{download_id}` | Delete Download |
| `POST` | `/api/v1/resources/{resource_id}/upload` | Upload Resource File |
| `GET` | `/api/v1/search/` | Search |
| `GET` | `/api/v1/search/suggestions` | Get Suggestions |
| `POST` | `/api/v1/search/viewed` | Mark As Viewed |
| `POST` | `/api/v1/support/` | Create Support Request |
| `GET` | `/health` | Health Check |
