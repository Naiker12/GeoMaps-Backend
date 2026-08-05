# GeoMaps Backend

Backend de GeoMaps construido con FastAPI, SQLAlchemy Async, PostgreSQL/PostGIS, Supabase y Google Gemini. Expone la API que alimenta el visor geoespacial, la gestión de proyectos, capas GIS, búsqueda, descargas, API keys, usuarios e IA.

Este README documenta la arquitectura real del backend por slices verticales (`app/Geo-*`), sus servicios, librerías, variables de entorno, comandos, rutas y responsabilidades.

## Tabla De Contenido

- [Funciones principales](#funciones-principales)
- [Stack técnico](#stack-técnico)
- [Arquitectura por slices verticales](#arquitectura-por-slices-verticales)
- [Estructura de carpetas](#estructura-de-carpetas)
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

| Módulo | Función |
| --- | --- |
| API REST | Expone rutas versionadas bajo `/api/v1`. |
| Autenticación (`Geo-Auth`) | Valida JWT de Supabase, sincroniza usuarios y protege rutas privadas. |
| Usuarios (`Geo-Usuarios`) | Gestiona perfiles y roles self-service del usuario final. |
| Proyectos (`Geo-Proyectos`) | CRUD de proyectos, ubicación, métricas, finanzas, ajustes de mapa, imágenes, modelos 3D y lotes. |
| Capas GIS (`Geo-Capas`) | Carga, almacena y consulta capas geográficas con features y geometría PostGIS. |
| Cartografía (`Geo-Cartografia`) | Generador de mapas, layouts, estilos e impresiones exportables. |
| Búsqueda (`Geo-Busqueda`) | Busca proyectos, lotes y features por texto o coordenadas. |
| Descargas (`Geo-Descargas`) | Administra recursos descargables, archivos y metadatos. |
| API Keys (`Geo-ApiKeys`) | Emite, revoca, audita y monitorea llaves de API del usuario. |
| IA (`Geo-IA`) | Chat, streaming, historial, sugerencias, herramientas y proveedor Gemini. |
| Reportes (`Geo-Reportes`) | Generación y exportación de reportes territoriales IA (Typst / PDF). |
| Soporte (`Geo-Soporte`) | Gestión de tickets de soporte enviados por los usuarios. |
| Storage (`Geo-Storage`) | Integra Supabase Storage para almacenamiento de archivos. |
| Geoprocesamiento (`Geo-Spatial`) | Operaciones geoespaciales y análisis de geometría. |
| OGC (`Geo-OGC`) | Proxy seguro para servicios OGC WMS/WFS. |

## Stack Técnico

| Librería / Herramienta | Versión | Uso en el proyecto |
| --- | --- | --- |
| FastAPI | `0.115.6` | Framework principal ASGI para API REST. |
| Uvicorn | `0.34.0` | Servidor ASGI local/producción. |
| SQLAlchemy | `2.0.36` | ORM async, modelos y consultas. |
| GeoAlchemy2 | `0.17.0` | Tipos y funciones geoespaciales para PostGIS. |
| Psycopg | `3.2.10` | Driver PostgreSQL async/binario. |
| Alembic | `1.14.0` | Migraciones de base de datos. |
| Redis | `5.2.1` | Cache/historial de conversaciones IA. |
| HTTPX | `0.28.1` | Cliente HTTP para JWKS de Supabase y llamadas externas. |
| Pandas | `2.2.3` | Procesamiento tabular de datos. |
| NumPy | `2.2.0` | Cálculo numérico. |
| Shapely | `2.0.6` | Manipulación de geometría. |
| PyProj | `3.7.1` | Transformaciones de coordenadas. |
| GeoPandas | `1.0.1` | Lectura/procesamiento de archivos geoespaciales. |
| Fiona | `1.10.1` | Lectura de formatos GIS como Shapefile. |
| python-multipart | `0.0.19` | Uploads `multipart/form-data`. |
| python-dotenv | `1.0.1` | Carga de variables desde `.env`. |
| pydantic-settings | `2.7.0` | Configuración tipada del entorno. |
| Supabase | `2.11.0` | Auth, storage y operaciones con Supabase. |
| Authlib | `1.3.2` | Manejo de JWT/JWK y soporte criptográfico. |
| google-genai | `>=1.0.0` | Cliente oficial para Google Gemini. |

## Arquitectura por Slices Verticales

El backend aplica una arquitectura de **slices verticales funcionales (`Geo-<Feature>`)**: cada dominio encapsula sus routers, servicios, schemas, repositorios y modelos en un mismo directorio autónomo.

| Dominio / Slice | Ubicación | Responsabilidad |
| --- | --- | --- |
| Entrada Principal | `app/main.py` | Configuración de FastAPI, middlewares CORS, lifespan y montaje de routers `Geo-*`. |
| Transversal Compartido | `app/shared/` | Configuración (`shared/core/config.py`), excepciones (`shared/core/exceptions.py`), logging (`shared/core/logging.py`), sesión DB (`shared/db/session.py`) y base repository (`shared/base_repository.py`). |
| Auth | `app/Geo-Auth/` | Autenticación, JWT Supabase y utilidades de seguridad. |
| Usuarios | `app/Geo-Usuarios/` | Modelo y perfil del usuario final. |
| Proyectos | `app/Geo-Proyectos/` | Gestión de proyectos territoriales, assets, finanzas y lotes. |
| Capas | `app/Geo-Capas/` | Modelos, repositorios y servicios de capas GIS. |
| Cartografía | `app/Geo-Cartografia/` | Generador de layouts de mapa, simbología y exportaciones. |
| Búsqueda | `app/Geo-Busqueda/` | Búsqueda geoespacial y por texto. |
| Descargas | `app/Geo-Descargas/` | Gestión de recursos descargables. |
| OGC | `app/Geo-OGC/` | Proxy seguro para servicios OGC. |
| IA | `app/Geo-IA/` | Agente IA, cliente LLM Gemini, historial y herramientas de mapas. |
| Reportes | `app/Geo-Reportes/` | Generación de reportes PDF e integración Typst. |
| Soporte | `app/Geo-Soporte/` | Tickets de soporte técnico del usuario. |
| API Keys | `app/Geo-ApiKeys/` | Gestión y auditoría de llaves de API. |
| Footprints | `app/Geo-Footprints/` | Huellas urbanas y polígonos. |
| Geo-Spatial | `app/Geo-Spatial/` | Utilidades y algoritmos de geoprocesamiento. |
| Storage | `app/Geo-Storage/` | Servicio de almacenamiento Supabase. |
| Geoportal | `app/Geo-Portal/` | Endpoints públicos del portal. |

## Estructura De Carpetas

```txt
app/
  Geo-ApiKeys/          Slice vertical de API Keys.
  Geo-Auth/             Slice vertical de Autenticación.
  Geo-Busqueda/         Slice vertical de Búsqueda espacial.
  Geo-Capas/            Slice vertical de Capas GIS.
  Geo-Cartografia/      Slice vertical de Generación Cartográfica.
  Geo-Descargas/        Slice vertical de Recursos Descargables.
  Geo-Footprints/       Slice vertical de Huellas de Proyectos.
  Geo-IA/               Slice vertical de Inteligencia Artificial (Gemini).
  Geo-OGC/              Slice vertical de Proxy OGC.
  Geo-Portal/           Slice vertical de Endpoints del Portal Público.
  Geo-Proyectos/        Slice vertical de Proyectos e Inmuebles.
  Geo-Reportes/         Slice vertical de Reportes Territorial/Typst.
  Geo-Soporte/          Slice vertical de Soporte Técnico.
  Geo-Spatial/          Slice vertical de Geoprocesamiento.
  Geo-Storage/          Slice vertical de Storage.
  Geo-Usuarios/         Slice vertical de Usuarios.
  shared/               Componentes genuinamente transversales (core, db, base_repository).
  main.py               Punto de entrada FastAPI.
alembic/                Migraciones de base de datos.
doc_backend_funciones/  Documentación por dominios sincronizada con Geo-*.
```

## Modelos Principales

| Modelo | Tabla | Función |
| --- | --- | --- |
| `User` | `users` | Perfil interno, rol, estado, datos personales y relación con Supabase. |
| `UserSession` | `user_sessions` | Sesiones de usuarios, IP, user agent y expiración. |
| `Project` | `projects` | Proyecto inmobiliario/territorial base. |
| `ProjectLocation` | `project_locations` | Coordenadas, geometría y URLs geoespaciales del proyecto. |
| `ProjectMetrics` | `project_metrics` | Áreas, niveles, unidades, avance, licencias y métricas. |
| `ProjectFinancials` | `project_financials` | Inversión, precio promedio y moneda. |
| `ProjectMapSettings` | `project_map_settings` | Color, opacidad, etiquetas y visualizador 3D. |
| `ProjectImage` | `project_images` | Imágenes asociadas al proyecto. |
| `ProjectModel3D` | `project_models_3d` | Modelos 3D asociados al proyecto. |
| `ProjectLot` | `project_lots` | Lotes con estado, precio, área, zona y geometría PostGIS. |
| `Layer` | `layers` | Metadatos de capa GIS, visibilidad, estilo, archivo y configuraciones. |
| `LayerFeature` | `layer_features` | Entidades individuales con propiedades JSONB y geometría PostGIS. |
| `DownloadResource` | `download_resources` | Recursos descargables, archivo, categoría, tags y publicación. |
| `APIKey` | `api_keys` | Llaves de API, rol, visibilidad, límites, estado y hash. |
| `APIKeyUsageLog` | `api_key_usage_logs` | Auditoría de uso por endpoint, método, estado, latencia e IP. |
| `APIKeyDailyStats` | `api_key_daily_stats` | Agregados diarios por llave. |
| `ActivityLog` | `activity_logs` | Eventos de actividad del sistema. |

## Referencia API

El backend expone una API versionada bajo `/api/v1`. La fuente de verdad interactiva es generada automáticamente por FastAPI:

```txt
http://localhost:8000/api/v1/docs
http://localhost:8000/api/v1/redoc
```

El estado básico del servicio se valida con:

```txt
GET /health
```

## Variables De Entorno

Crear `.env` en la raíz del backend:

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

| Variable | Obligatoria | Descripción |
| --- | --- | --- |
| `DATABASE_URL` | Sí | Conexión PostgreSQL/PostGIS. |
| `SUPABASE_URL` | Sí | URL del proyecto Supabase. |
| `SUPABASE_ANON_KEY` | Sí | Llave anónima para operaciones de auth. |
| `SUPABASE_SERVICE_KEY` | Recomendada | Llave service role para storage. |
| `SUPABASE_JWT_SECRET` | Sí | Secreto usado para validar tokens Supabase. |
| `JWT_SECRET` / `SECRET_KEY` | Recomendada | Secreto para tokens locales. |
| `GOOGLE_API` | Si usa IA | API key de Google Gemini. |
| `FRONTEND_URL` | Recomendada | URL del frontend para CORS. |
| `BACKEND_CORS_ORIGINS` | Recomendada | Lista de orígenes permitidos. |

## Instalacion Y Ejecución

Requisitos recomendados:

- Python 3.11 o superior.
- PostgreSQL con extensión PostGIS.
- Redis si se usa historial/cache de IA.
- Proyecto Supabase configurado.

Windows PowerShell:

```powershell
cd GeoMaps-Backend
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

## Base De Datos Y Migraciones

El proyecto usa SQLAlchemy async y Alembic.

Comandos comunes:

```bash
alembic upgrade head
alembic revision --autogenerate -m "descripcion_del_cambio"
alembic downgrade -1
```

## Autenticacion Y Seguridad

Mecanismos soportados:

| Mecanismo | Uso |
| --- | --- |
| JWT Supabase | Autenticación del frontend, perfil de usuario y rutas privadas. |
| API Key | Acceso programático y auditoría de consumo por endpoint. |

## IA

La capa IA vive dentro del slice vertical `app/Geo-IA/`.

Responsabilidades:

- Construir prompts con contexto geoespacial de GeoMaps.
- Enviar mensajes a Google Gemini mediante `google-genai`.
- Soportar streaming y respuestas estructuradas.
- Mantener historial de conversaciones con Redis (`history_service.py`).
- Ejecutar herramientas del mapa traducibles por el frontend (`tools/`).

## Relacion Con El Frontend

El frontend consume este backend bajo:

```txt
http://localhost:8000/api/v1
```

CORS debe permitir los orígenes del frontend:

```txt
http://localhost:5173
http://127.0.0.1:5173
```
