# GeoMaps Backend

Backend de GeoMaps construido con FastAPI, SQLAlchemy Async, PostgreSQL/PostGIS, Supabase y Google Gemini. Expone la API que alimenta el visor geoespacial, el panel administrativo, la gestion de proyectos, capas GIS, busqueda, descargas, API keys, usuarios, analitica e IA.

Este README documenta la arquitectura real del backend, sus servicios, librerias, variables de entorno, comandos, rutas y responsabilidades.

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

## Funciones Principales

| Modulo | Funcion |
| --- | --- |
| API REST | Expone rutas versionadas bajo `/api/v1`. |
| Autenticacion | Valida JWT de Supabase, sincroniza usuarios y protege rutas privadas. |
| Usuarios | Gestiona perfiles, roles, sesiones y operaciones administrativas. |
| Proyectos | CRUD de proyectos, ubicacion, metricas, finanzas, ajustes de mapa, imagenes, modelos 3D y lotes. |
| Capas GIS | Carga, almacena y consulta capas geograficas con features y geometria PostGIS. |
| Busqueda | Busca proyectos, lotes y features por texto o coordenadas. |
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
| Redis | `5.2.1` | Cache/historial de conversaciones IA. |
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
| Servicios | `app/services` | Reglas de negocio: proyectos, capas, descargas, busqueda, IA, analitica. |
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

## Servicios Del Backend

| Archivo / Modulo | Responsabilidad |
| --- | --- |
| `app/services/project_service.py` | Gestion de proyectos, relaciones, uploads y lotes. |
| `app/services/layer_service.py` | Carga, edicion y consulta de capas GIS. |
| `app/services/geo_service.py` | Procesamiento geoespacial y conversion de datos. |
| `app/services/search_service.py` | Busqueda global por texto/coordenadas. |
| `app/services/download_service.py` | Metadatos de recursos descargables. |
| `app/services/download_storage_service.py` | Upload/list/remove de archivos de descargas en Supabase Storage. |
| `app/services/storage_service.py` | Servicio general de storage Supabase. |
| `app/services/api_key_service.py` | Creacion, revocacion, estadisticas y logs de API keys. |
| `app/services/analytics/*` | Resumenes, actividad, dashboards y metricas administrativas. |
| `app/services/ia/agent_service.py` | Orquestacion principal del chat IA. |
| `app/services/ia/history_service.py` | Historial de conversaciones con Redis. |
| `app/services/ia/prompt_builder.py` | Construccion de prompts y contexto. |
| `app/services/ia/tools_service.py` | Ejecucion de herramientas/acciones IA. |
| `app/services/ia/usage_service.py` | Medicion de uso IA. |
| `app/infrastructure/ia_llm_client.py` | Cliente/factory del proveedor Gemini con `google-genai`. |
| `app/application/auth/service.py` | Sincronizacion de usuario con Supabase Auth. |

## Modelos Principales

| Modelo | Tabla | Funcion |
| --- | --- | --- |
| `User` | `users` | Perfil interno, rol, estado, datos personales y relacion con Supabase. |
| `UserSession` | `user_sessions` | Sesiones de usuarios/admins, IP, user agent y expiracion. |
| `Admin` | `admins` | Administradores internos cuando aplica. |
| `Project` | `projects` | Proyecto inmobiliario/territorial base. |
| `ProjectLocation` | `project_locations` | Coordenadas, geometria y URLs geoespaciales del proyecto. |
| `ProjectMetrics` | `project_metrics` | Areas, niveles, unidades, avance, licencias y metricas. |
| `ProjectFinancials` | `project_financials` | Inversion, precio promedio y moneda. |
| `ProjectMapSettings` | `project_map_settings` | Color, opacidad, etiquetas y visualizador 3D. |
| `ProjectAdminSettings` | `project_admin_settings` | Visibilidad publica, destacado y prioridad. |
| `ProjectImage` | `project_images` | Imagenes asociadas al proyecto. |
| `ProjectModel3D` | `project_models_3d` | Modelos 3D asociados al proyecto. |
| `ProjectLot` | `project_lots` | Lotes con estado, precio, area, zona y geometria PostGIS. |
| `Layer` | `layers` | Metadatos de capa GIS, visibilidad, estilo, archivo y configuraciones. |
| `LayerFeature` | `layer_features` | Entidades individuales con propiedades JSONB y geometria PostGIS. |
| `DownloadResource` | `download_resources` | Recursos descargables, archivo, categoria, tags y publicacion. |
| `APIKey` | `api_keys` | Llaves de API, rol, visibilidad, limites, estado y hash. |
| `APIKeyUsageLog` | `api_key_usage_logs` | Auditoria de uso por endpoint, metodo, estado, latencia e IP. |
| `APIKeyDailyStats` | `api_key_daily_stats` | Agregados diarios por llave. |
| `ActivityLog` | `activity_logs` | Eventos de actividad del sistema. |

## Referencia API

El backend expone una API versionada bajo `/api/v1`, pero este README no mantiene un inventario manual de rutas. La fuente de verdad es la documentacion interactiva generada por FastAPI:

```txt
http://localhost:8000/api/v1/docs
http://localhost:8000/api/v1/redoc
```

En produccion, usar la URL publica del servicio:

```txt
https://geomaps-backend.onrender.com/api/v1/docs
```

El estado basico del servicio se valida con:

```txt
GET /health
```

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
| `JWT_SECRET` / `SECRET_KEY` | Recomendada | Secreto para tokens locales y utilidades de seguridad. |
| `GOOGLE_API` | Si usa IA | API key de Google Gemini. |
| `FRONTEND_URL` | Recomendada | URL del frontend para CORS y callbacks. |
| `BACKEND_CORS_ORIGINS` | Recomendada | Lista de origenes permitidos separados por coma o JSON list. |

### Supabase En Render

Render no soporta conexiones IPv6 salientes para este caso. Si `DATABASE_URL` apunta a `db.<project-ref>.supabase.co:5432`, Supabase puede resolverlo a IPv6 y la app falla con `Network is unreachable`.

En Supabase Dashboard -> Project Settings -> Database -> Connection string, copia una URL de pooler:

- Session pooler para este backend persistente: `postgres://postgres.<project-ref>:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:5432/postgres`
- Transaction pooler si prefieres puerto `6543`: `postgres://postgres.<project-ref>:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres`

Pega esa URL como `DATABASE_URL` en Render. El backend desactiva prepared statements automaticamente cuando detecta el transaction pooler `:6543`.

## Instalacion Y Ejecucion

Requisitos recomendados:

- Python 3.11 o superior.
- PostgreSQL con extension PostGIS.
- Redis si se usa historial/cache de IA.
- Proyecto Supabase configurado.

Windows PowerShell:

```powershell
cd C:\Users\gomez\Downloads\GeoMaps-Backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Linux/macOS:

```bash
cd GeoMaps-Backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
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
alembic upgrade head
alembic revision --autogenerate -m "descripcion_del_cambio"
alembic downgrade -1
```

Consideraciones:

- La base de datos debe tener PostGIS habilitado.
- Las geometrias principales usan SRID `4326`.
- Las entidades GIS usan `JSONB` para propiedades flexibles.
- `LayerFeature.geom` y geometria de proyectos/lotes deben tener indices espaciales para buen rendimiento.

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
4. Si el usuario no existe internamente, se sincroniza desde Supabase.
5. Las rutas administrativas verifican rol antes de permitir operaciones.
6. Las API keys se envian con `X-API-Key` o `api_key`.
7. El middleware registra uso exitoso o intento fallido.

## IA

La capa IA se concentra en `app/services/ia` e `app/infrastructure/ia_llm_client.py`.

Responsabilidades:

- Construir prompts con contexto de GeoMaps.
- Enviar mensajes a Google Gemini usando `google-genai`.
- Soportar respuesta normal y streaming.
- Mantener historial de conversaciones con Redis.
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
