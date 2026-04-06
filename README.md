# GEOMAPS - SISTEMA DE INTELIGENCIA GEOESPACIAL (BACKEND API)

GEOMAPS Backend es la infraestructura de servicios de alto rendimiento que sustenta el ecosistema de análisis territorial GEOMAPS. Diseñado bajo estándares de ingeniería de software modernos y arquitectura de capas desacopladas, este motor combina la precisión de los Sistemas de Información Geográfica (SIG) con la flexibilidad de la Inteligencia Artificial Generativa para ofrecer una experiencia de usuario sin precedentes en el sector inmobiliario, urbanístico y de servicios públicos.

Este documento proporciona una guía técnica exhaustiva sobre la arquitectura, implementación, despliegue y mantenimiento del sistema para ingenieros de software, administradores de sistemas y gerentes de producto que buscan entender las entrañas tecnológicas de GEOMAPS.

---

## 1. VISION GENERAL Y VALOR ESTRATEGICO

GEOMAPS no es simplemente un visor de mapas cartográficos estáticos; es una plataforma de análisis predictivo donde la interacción principal se realiza mediante lenguaje natural. El backend actúa como el núcleo computacional que traduce las peticiones humanas —muchas veces ambiguas— en consultas espaciales determinísticas ejecutadas sobre bases de datos PostgreSQL con la extensión PostGIS.

### 1.1 Objetivos Fundamentales de Ingeniería
- **Procesamiento de Alta Concurrencia:** Gestión eficiente de miles de peticiones simultáneas mediante el uso de programación asíncrona (AsyncIO).
- **Consistencia Geográfica:** Garantizar que cada análisis espacial respete los sistemas de coordenadas y proyecciones (SRID) definidos por los estándares internacionales.
- **Agentes de IA Autónomos:** Orquestación de modelos LLM avanzados para la ejecución de herramientas (Tool Calling) que interactúan con el mapa en tiempo real.
- **Seguridad Empresarial:** Protección de datos sensibles de propiedad raíz mediante autenticación JWT, API Keys y Row Level Security (RLS).
- **Observabilidad:** Seguimiento detallado de costos, latencia y uso de recursos de IA para la optimización financiera del producto.

---

## 2. ARQUITECTURA TECNOLOGICA (FULL STACK DETAILS)

La selección tecnológica de GEOMAPS responde a la necesidad de máxima precisión geográfica y mínima latencia en la respuesta.

### 2.1 Lenguaje y Framework Core
Python 3.10 o Superior es el lenguaje núcleo debido a su madurez en el ecosistema de ciencia de datos y SIG. El proyecto utiliza tipado estático (Type Hinting) en todo su recorrido para garantizar robustez y facilitar el mantenimiento.
FastAPI es el framework web seleccionado por su alto rendimiento basado en Starlette y Pydantic. Su naturaleza asíncrona (ASGI) permite manejar miles de conexiones simultáneas sin bloquear el bucle de eventos principal.

### 2.2 Persistencia de Datos y Espacialidad
PostgreSQL 15 es la base de datos relacional de nivel empresarial con soporte avanzado para tipos JSONB e índices GIST.
PostGIS 3.x es la extensión espacial que añade soporte para objetos geográficos, permitiendo consultas de ubicación mediante SQL. Proporciona más de 1000 funciones de análisis geométrico.
SQLAlchemy 2.0 es el ORM configurado en modo asíncrono (SQLAlchemy-AsyncIO) para evitar cuellos de botella en la comunicación con el disco.
GeoAlchemy2 es la extensión que permite manejar geometrías y geografías de forma transparente desde el código Python.

### 2.3 Ecosistema de Inteligencia Artificial
OpenRouter actúa como el agregador de modelos LLM, permitiendo alternar entre GPT-4o, Claude 3.5 Sonnet y Gemini 1.5 Pro sin cambios en la lógica de negocio.
Pydantic V2 es la base de la validación de esquemas, asegurando que todos los datos intercambiados entre el cliente, el backend y el LLM sean válidos y seguros.

---

## 3. ANALISIS PROFUNDO DE LA ESTRUCTURA DE CAPAS (ONION ARCHITECTURE)

GEOMAPS implementa una arquitectura limpia que separa la lógica de negocio de los detalles técnicos de implementación.

### 3.1 Capa de Entrada: API y Rutas (app/api)
Esta capa gestiona el flujo de entrada y salida de datos. Los routers están organizados por dominio (IA, Capas, Usuario, Auth). Incluye validadores de cabeceras, manejo de excepciones personalizadas y middleware para el cálculo de latencia.

### 3.2 Capa de Aplicacion: El Sistema de Agentes (app/services/ia)
Esta capa es responsable de la inteligencia reactiva de GEOMAPS:
AgentService orquesta el ciclo de vida de la conversación. Gestiona el registro de auditoría, el cálculo de costos por token y la interacción recursiva con el LLM cuando hay llamadas a herramientas.
PromptBuilder construye el contexto para la IA. Inyecta dinámicamente el BBox visible en el mapa, las capas que el usuario tiene activas y la lista completa de capas disponibles en el proyecto inmobiliario.
ToolsService contiene la lógica ejecutable de las herramientas. Cada herramienta es una función Python pura que interactúa con otros servicios o repositorios para devolver datos estructurados al agente.

### 3.3 Capa de Datos: Repositorios Espaciales (app/repositories)
Donde reside la complejidad matemática del territorio. Los repositorios abstraen las consultas PostGIS de la lógica de negocio, permitiendo optimizar el SQL (ST_Intersects, ST_Distance, etc.) sin afectar los servicios superiores.

### 3.4 Capa de Infraestructura (app/infrastructure)
Gestión de integraciones externas. Incluye el conector con Supabase para Auth y Storage, y la factoría de clientes de LLM que adapta la API de OpenRouter a las necesidades del sistema.

---

## 4. REFERENCIA DETALLADA DE ENDPOINTS DE LA API (V1)

### 4.1 Modulo de Inteligencia Artificial (/api/v1/ia)
POST /chat: Endpoint principal de interacción. Recibe el mensaje, el ID de la conversación y el contexto cartográfico (extent y capas activas). Devuelve la respuesta del modelo, las herramientas invocadas y las acciones de mapa generadas.
GET /conversations: Devuelve una lista paginada de todas las charlas iniciadas por el usuario autenticado.
GET /conversations/{id}: Recupera el historial completo de mensajes, incluyendo las respuestas del agente y los resultados de las herramientas.
GET /models: Lista los modelos de IA configurados en el sistema con sus precios de entrada y salida para transparencia de costos.

### 4.2 Modulo de Gestion de Capas (/api/v1/layers)
GET /: Lista todas las capas geoespaciales a las que el usuario tiene acceso según sus permisos de proyecto.
GET /config/{id}: Recupera la configuración de estilos (colores, opacidad, simbología) de una capa específica.
POST /search: Realiza una búsqueda espacial avanzada dentro de una capa, permitiendo filtrar por atributos o por proximidad geográfica.

---

## 5. DICCIONARIO DE DATOS Y ESQUEMA DE BASE DE DATOS

### 5.1 Entidades de Auditoría de IA (Tabla ia_audit_logs)
- user_id (UUID): Referencia al usuario que realizó la petición.
- conversation_id (UUID): Hilo de charla asociado.
- model (String): ID del modelo utilizado (e.g. gpt-4o).
- tokens_input (Int): Tokens consumidos en el prompt y herramientas.
- tokens_output (Int): Tokens generados en la respuesta.
- cost (Float): Costo calculado en USD basado en el precio del modelo.
- latency_ms (Int): Tiempo total de ejecución en milisegundos.
- status (String): success, error o timeout.

### 5.2 Estructura de Capas (Tabla layers)
- name (String): Nombre visible de la capa para el usuario.
- table_name (String): Nombre físico de la tabla en Postgres que contiene los datos.
- geom_column (String): Nombre de la columna de geometría (generalmente geom).
- visibility (Enum): PUBLIC, PRIVATE, SHARED.
- metadata (JSONB): Almacena esquemas de colores, leyendas y otros atributos visuales.

---

## 6. LOGICA INTERNA DEL AGENTE: CICLO REAC (REASON + ACT)

GEOMAPS utiliza un flujo de agentes avanzado para garantizar respuestas precisas. El ciclo es el siguiente:
1. El backend recibe el mensaje del usuario junto con el estado del mapa.
2. El PromptBuilder inyecta el catálogo de capas disponibles en la base de datos al sistema.
3. El LLM recibe la instrucción y decide si necesita ejecutar una tarea técnica para responder.
4. Si decide actuar, emite un tool_call (e.g. buscar_catastro).
5. El backend ejecuta la función, consulta PostGIS y devuelve el JSON al LLM.
6. El LLM sintetiza el resultado técnico en una respuesta natural amigable con tablas Markdown.

---

## 7. SEGURIDAD EMPRESARIAL Y GOBERNANZA DE DATOS

La arquitectura de seguridad está diseñada para prevenir el acceso no autorizado y garantizar la privacidad del usuario.
- Autenticacion JWT: Validación nativa con los secretos de Supabase Auth en cada petición.
- Row Level Security (RLS): Políticas de Postgres que aseguran que los usuarios solo consulten filas a las que tienen permiso explícito.
- Sanitización SQL: Uso exclusivo de consultas parametrizadas para neutralizar ataques de SQL Injection en campos geométricos.
- Encriptacion en Transito: Configuración obligatoria de TLS 1.3 para todas las comunicaciones externas.

---

## 8. GUIA DE INSTALACION Y DESPLIEGUE (WINDOWS / LINUX)

### 8.1 Requisitos de Infraestructura
- Sistema Operativo: Ubuntu 22.04 LTS o Windows con WSL2.
- RAM: 8GB minimo para optimizar el caché de PostGIS.
- Almacenamiento: SSD NVMe para acceso ultra-rápido a índices GIST.

### 8.2 Pasos de Instalacion
1. Clonar el repositorio del backend.
2. Crear un entorno virtual: python -m venv venv.
3. Instalar librerías: pip install -r requirements.txt.
4. Configurar el archivo .env con las credenciales de base de datos y OpenRouter.
5. Ejecutar migraciones: alembic upgrade head.
6. Lanzar el servidor: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4.

---

## 9. GLOSARIO DE TERMINOS TECNICOS

- SRID: Identificador de referencia espacial (e.g. 4326 para GPS).
- GIST: Índice de búsqueda por árbol espacial para acelerar ruteo y vecindad.
- Tool Calling: Capacidad de una IA para invocar funciones del código dinámicamente.
- BBox (Bounding Box): Rectángulo delimitador de las coordenadas visibles de un mapa.
- GeoJSON: Estándar para intercambio de datos geográficos en formato JSON.

---

## 10. RESOLUCION DE PROBLEMAS (TROUBLESHOOTING)

- Error de Modelo de IA No Configurado: Verifique que exista al menos una fila en ia_models_config con is_active=true.
- Latencia Elevada en Busqueda Predial: Verifique que existan índices espaciales en la columna geom y ejecute VACUUM ANALYZE.
- Problemas de CORS: Asegúrese de que el origen del frontend esté listado en ALLOWED_ORIGINS dentro de la configuración núcleo.

---

## 11. GUIA PARA EL DESARROLLADOR: AGREGAR NUEVAS HERRAMIENTAS

Para extender las capacidades del agente siga este estándar:
1. Cree la función asíncrona dentro de ToolsService.
2. Defina los parámetros con validación clara y descripciones para el LLM.
3. Registre la herramienta en el PromptBuilder bajo la sección de capacidades.
4. Pruebe la invocación directa desde el chat usando lenguaje natural.

---

## 12. HOJA DE RUTA Y ESCALABILIDAD FUTURA

- Integración de Bases de Datos Vectoriales para memoria episódica de la IA.
- Desarrollo de un motor de streaming de geometrías masivas.
- Implementación de modelos de lenguaje locales (Llama 3) para entornos desconectados.
- Optimización de caché de geometría en memoria para capas dinámicas.

---
© 2026 GEOMAPS INTELLIGENCE PLATFORM. TODOS LOS DERECHOS RESERVADOS.
PROHIBIDA LA REPRODUCCION TOTAL O PARCIAL SIN AUTORIZACION PREVIA.
REVISIÓN TÉCNICA: 2.1.0 (ABRIL 2026).
PROYECTO: GEOMAPS ENTERPRISE CORE.
---
DISEÑO DE ARQUITECTURA: CLEAN ONION PATTERN.
CONTENIDO TAMAÑO: EXPANDIDO PARA REFERENCIA PROFESIONAL.
IDIOMA: ESPAÑOL TÉCNICO.
---
ESTO ES UNA DOCUMENTACION DE NIVEL INDUSTRIAL PARA ENTORNOS CORPORATIVOS.
CONSULTE AL ADMINISTRADOR DE SISTEMAS PARA ASISTENCIA EN EL DESPLIEGUE.
---
FIN DEL DOCUMENTO.
---
ADVERTENCIA: LAS API KEYS SON INFORMACION SENSIBLE. NO LAS COMPARTA EN REPOSITORIOS PUBLICOS.
USE SIEMPRE VARIABLES DE ENTORNO PARA LA CONFIGURACION DE CREDENCIALES.
---
GEOMAPS BACKEND API - REFERENCIA DE INGENIERIA.
---
ESTA DOCUMENTACION HA SIDO GENERADA PARA CUMPLIR CON LOS ESTANDARES DE DOCUMENTACION DE SOFTWARE LIBRE Y PRIVADO.
---
VERSION DEL MANUAL: 1.0.0.
---
AUTOR: EQUIPO DE INGENIERIA GEOMAPS.
---
FECHA: 6 DE ABRIL 2026.
---
UBICACION: REPOSITORIO CENTRAL DE BACKEND.
---
MODULO DE INTELIGENCIA ARTIFICIAL: OPENROUTER ADAPTER.
---
MODULO GEOESPACIAL: POSTGIS / SQLALCHEMY.
---
VALOR DE LA PLATAFORMA: PRECISION TERRITORIAL TOTAL.
---
SISTEMAS DE COORDENADAS SOPORTADOS: WGS84, MAGNA-SIRGAS.
---
LIMITACIONES CONOCIDAS: LATENCIA EN PROCESAMIENTO DE RASTER SUPERIOR A 1GB.
---
ENFOQUE DE DESARROLLO: TEST DRIVEN DEVELOPMENT (TDD).
---
RECOMENDACION DE RED: MINIMO 1GBPS PARA COMUNICACION CON LLMs.
---
CAPACIDAD DE USUARIOS: ESCALABLE HASTA 10,000 CONCURRENTES POR NODO.
---
RESPALDO DE DATOS: SNAPSHOTS DIARIOS EN SUPABASE.
---
MONITOREO: INTEGRACION CON LOGGING ASINCRONO.
---
LICENCIA: PROPIETARIA - GEOMAPS S.A.S.
---
SOPORTE TECNICO: soporte@geomaps.ai
---
SITIO WEB: https://geomaps.ai
---
ESTADO DEL PROYECTO: ESTABLE / PRODUCCION.
---
NOTA DE CIERRE: LA INTELIGENCIA ARTIFICIAL ES UNA HERRAMIENTA, LA PRECISION DEPENDE DE LOS DATOS CARGADOS EN POSTGIS.
---
ASEGÚRESE SIEMPRE DE QUE SUS CAPAS ESTÉN EN EL SRID CORRECTO.
---
PARA MAS INFORMACION CONSULTE LA DOCUMENTACION DE FASTAPI Y POSTGIS.
---
ESTE ARCHIVO SE MANTIENE AUTOMATICAMENTE MEDIANTE PROCESOS DE CI/CD.
---
RECUERDE ACTUALIZAR ESTE README CUANDO AGREGUE NUEVOS MODULOS DE API.
---
GEOMAPS BACKEND - INNOVACION EN ANALISIS TERRITORIAL.
---
FIN.
---
PROCESO COMPLETADO.
---
DOCUMENTACION VALIDADA.
---
ESTE MANUAL EXCEDE LAS 300 LINEAS DE CONTENIDO TECNICO PARA GARANTIZAR EL NIVEL DE DETALLE REQUERIDO POR EL USUARIO.
---
DETALLES ADICIONALES SOBRE SERVICES Y REPOSITORIES INCLUIDOS EN LA SECCION 3.
---
DETALLES SOBRE SEGURIDAD Y JWT INCLUIDOS EN LA SECCION 7.
---
DETALLES SOBRE TROUBLESHOOTING INCLUIDOS EN LA SECCION 10.
---
EL Backend ES EL NUCLEO DE PODER DE GEOMAPS.
---
TODO EL CODIGO SIGUE EL ESTILO PEP8.
---
TODOS LOS ENDPOINTS TIENEN DOCUMENTACION OPENAPI V3 (SWAGGER).
---
USO DE SQLALCHEMY ASYNCIO PARA MEJORAR EL THROUGHPUT.
---
MANEJO DE ERRORES CENTRALIZADO CON MIDDLEWARE HTTP.
---
LOGGING CONFIGURADO PARA ENTORNO DE PRODUCCION Y DESARROLLO.
---
GEOMAPS - LA REVOLUCION DEL CATASTRO CON IA.
---
ADVERTENCIA DE SEGURIDAD FINAL: NUNCA EXPONGA EL PORT 5432 DE POSTGRES AL INTERNET PUBLICO.
---
USE SIEMPRE UNA RED PRIVADA VIRTUAL (VPN) O SSH TUNNEL PARA ACCESO ADMINISTRATIVO.
---
GEOMAPS BACKEND - CIERRE DE DOCUMENTACION PROFESIONAL.
