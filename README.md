# GEOMAPS - MOTOR DE BACKEND Y HUB DE INTELIGENCIA (OSGS)

El Backend de GEOMAPS (Open SaaS Geo System) constituye la espina dorsal computacional y de seguridad de nuestra plataforma de análisis catastral y predictivo. Diseñado estrictamente bajo una arquitectura monolítica modular asíncrona, este sistema soporta miles de polígonos concurrentes, cálculos geográficos vectoriales y procesos in-memory intensivos. Se abandona por completo el patrón clásico MVC en favor de una **Arquitectura en Capas Limpias (Clean Architecture / Onion)** con fuertes principios SOLID y separación transaccional de bases de datos.

Este documento de ingeniería presenta, en profundidad y con máximo rigor técnico, la toma de decisiones, la estructura, y el funcionamiento atómico interno de las APIs y del orquestador de Inteligencia Artificial que potencia el servicio.

---

## 1. ORQUESTACIÓN Y DESPLIEGUE CONTINUO (DEVOPS & LOCAL DEV)

La inicialización del sistema aísla por completo el motor para prevenir contaminación de dependencias en el kernel operativo. 

### 1.1 Secuencia de Comandos (Entorno Basado en Windows/WSL)

```bash
# 1. Posicionamiento en el Directorio Raíz del Repositorio de Servicios
cd GeoMaps-Backend

# 2. Virtualización de Entorno (Requerido Python 3.10 o superior)
# Este paso crea la burbuja de dependencias exclusivas para el SDK espacial y ML.
python -m venv venv

# 3. Activación Rigurosa del Entorno (PowerShell o CMD)
.\venv\Scripts\activate

# 4. Ingesta Transaccional de Paquetes Core (ASGI, Computación y Logging)
pip install -r requirements.txt

# 5. Arranque Simultáneo: Compilación en Caliente y Activación de Sockets
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --reload
uvicorn app.main:app --reload   
```
Al finalizar la ejecución, los metadatos y el Swagger automatizado (OpenAPI) quedarán mapeados en `http://localhost:8000/docs`, listos para auditar las colecciones de endpoints POST, GET, PUT y DELETE en tiempo real.

---

## 2. MATRIZ DE RECHAZO: ¿POR QUÉ ELEGIMOS ESTAS PIEZAS DE HARDWARE Y SOFTWARE?

Para asegurar latencias sub-milisegundo en las consultas SIG (Sistemas de Información Geográfica), se descartaron arquitecturas populares que imponen sobrecarga (bloqueo del `event loop`) al procesar cálculos matemáticos masivos.

| Componente Selecto | Solución Rechazada / Común | Justificación Técnica Exhaustiva |
| :--- | :--- | :--- |
| **FastAPI** | Flask, Django | Al manejar streams de Inteligencia Artificial y consultas pesadas, Python con Django se convierte en un cuello de botella sincrónico bloqueante. FastAPI (con Starlette subyacente) resuelve esto con el padrão *ASGI* y concurrencia `async/await`, permitiendo despachar consultas a OpenAI sin paralizar otras búsquedas catastrales simultáneas. Pydantic embebido valida la basura entrante antes de tocar la red lógica. |
| **Pydantic V2** | Marshmallow, DRF Ser. | Reescribido en lenguaje Rust, multiplica por 50x la velocidad de las validaciones de JSONs y Geometrías (ej: features de polígonos extensos). Fallar temprano (*fail fast*) e imposibilitar colapsos (*Type Errors*) profundos. |
| **PostgreSQL 15** | MySQL, MongoDB | Postgres no tiene rival para GIS empresarial. MongoDB flaquea espantosamente al lidiar con topología multipolígono. Postgres nos provee tipos masivos JSONB relacionales y un motor atómico, crucial en transacciones bancarias-inmobiliarias para asegurar la propiedad (ACID compliance extremo). |
| **PostGIS 3.x** | Cálculos C++ externos | PostGIS introduce comandos espaciales directamente en las Query SQL (`ST_Intersects`, `ST_Buffer`), logrando que el hardware de disco filtre áreas sin tener que cargar la geometría entera a la memoria RAM de Python, ahorrando decenas de Gigabytes en cálculos urbanísticos abstractos. |
| **YOLOv8** | Faster R-CNN, SSD | Nuestro motor autónomo de segmentación urbanística (vehículos, techos) requería inferencia a la mayor cantidad posible de *Frames Per Second* (FPS). YOLOv8 ofrece precisión de Estado del Arte (*SOTA*) en detecciones compactas. |
| **OpenRouter** | Azure OpenAI Integrado | El ruteador abierto nos dota de resiliencia Anti-Caídas. Si GPT-4o experimenta apagones parciales de servidor, redireccionamos el motor a Anthropic Claude 3.5 mediante lógica local silenciosa. Elimina el riesgo de obsolescencia de un solo modelo. |
| **Supabase** | Firebase / AWS Cognito | Provee JWT instantáneos emparejados a RLS de la base de datos subyacente de Postgres de forma 100% simétrica, evitando los sobrecostos de Middleware en servidores serverless. |

---

## 3. ANÁLISIS DE LA ESTRUCTURA EN CAPAS CEBOLLA (CLEAN ARCHITECTURE)

La separación brutal del código garantiza mantenibilidad. Cada módulo ignora por completo lo que sucede en el nivel superior, protegiendo así los modelos de base de datos de las respuestas Web.

### 3.1 Nivel 1: Dominio de Routers (La Puerta HTTP) - `/app/api/`
Maneja de manera puramente aséptica las peticiones serializadas provenientes de React. Extrae los Headers (Tokens JWT), sanitiza malwares rudimentarios y entrega los paquetes al corazón de negocio.
- **NO hay** operaciones a bases de datos aquí. Si necesitas una modificación, llama un Servicio.

### 3.2 Nivel 2: Casos de Negocio Inteligentes (Services) - `/app/services/`
- **Servicios de Mapas:** Extraen lotificaciones, cruzan datos de estratificación y ejecutan limpieza algorítmica de campos nulos (`NULL`) provenientes del motor SIG.
- **Agentes GPT (ReAct):** Interpreta los "Prompts" humanos. Modifica la Temperatura (0.1 para buscar datos numéricos exactos, 0.7 para análisis sociodemográficos especulativos). Genera la invocación de herramientas (`Function Calling/Tools`) enviando el encuadre matemático interactivo del usuario (`BBox`).

### 3.3 Nivel 3: El Almacén Epistémico (Repositories) - `/app/repositories/`
- Alberga los métodos `SQLAlchemy AsyncSession`.
- Todas las inyecciones de dependencias aterrizan aquí, traduciendo una solicitud lógica de "Buscar predio por valor" a un sofisticado script SQL asíncrono, garantizando el aislamiento criptográfico anti-inyecciones.

---

## 4. ESTÁNDARES CONTRACTUALES Y CONTROL DE AUDITORÍA (TELEMETRÍA)

La plataforma incluye en su diseño un escrutinio forense y financiero para cada llamado algorítmico, fundamental en aplicaciones que fungen como un Software Productivo.

### 4.1 Log de Ejecución de Inteligencia Artificial (`ia_audit_logs`)
Un registro transaccional obligatorio que persiste cada *Token* inyectado en el LLM:
1. `User_UUID`: Dueño del mensaje para cargo y limitación (Rate Limiting).
2. `Model_Invoked`: Firma de la red conectada en ese frame (e.g. `openai/gpt-4o`).
3. `Cost_USD`: Traducción hiperprecisa del millar de tokens gastados calculada tras el cierre de Stream de Respuesta, cruzada contra `ia_models_config`.
4. `Latency_Chronometer`: Registro sub-microsegundo para medir fatiga temporal y aplicar bloqueos automáticos en caso de latencias letales (> 40 segundos).

### 4.2 Gobernanza Geográfica: Privacidad de Roles y Filtros Geográficos
Todo el ecosistema geográfico filtra capas en segundo plano antes de enviarse al usuario mediante Row Level Security. Un token administrativo posee lectura ilimitada a mallas espaciales completas de Cartagena, mientras un usuario público ve la cuadrícula truncada o denegada geográficamente (Blindaje nativo de PostgreSQL RLS).

---

## 5. REPRODUCCIÓN MECÁNICA Y SOLUCIÓN DE BLOQUEOS (TROUBLESHOOTING)

El motor provee salvavidas de diagnóstico rápido para garantizar *Uptime* de los nodos locales.

- **Falla Crítica de Compilación (Error en C inicialización C++):**
  Asegurarse de tener preinstalado el paquete oficial de "Desktop Development with C++" de Microsoft Visual Studio Build Tools, vitalicio para precompilar librerías de análisis y validación (Ujson, PsycoPG2, Tensorflows).

- **502 Bad Gateway / Connection Reset Error:**
  Probable saturación por tiempo de espera (*Connection Timeout*). Verifique el estrangulamiento de los puentes locales y deshabilite la depuración *Watchdog* extra si el IDE de desarrollo impone frenos, elevando explícitamente `--timeout-keep-alive 600` en Uvicorn.

- **Pérdida De Contexto JWT:**
  La aplicación asume el Bearer Header bajo la clave `Authorization`. Asegurarse categóricamente mediante un inspector que la firma HMAC coincida paramétricamente con el perfil remoto provisto desde Supabase (Chequeo local de criptografía por algoritmo RSA256).

---

## 6. EXPANSIÓN Y CRECIMIENTO ALGORÍTMICO (ROADMAP FUTURO)

Actualmente, las refactorizaciones de escalamiento in-memory y procesamiento vector están listas para ejecutarse:

1. **Adopción de Almacenamiento Vectorizado:**
   Implementar la extensión oficial `pgvector` sobre PostgreSQL integrando "Embeddings" profundos del historial del chat y propiedades complejas, llevando la deducción semántica predial hasta un paradigma `RAG` (Retrieval-Augmented Generation) avanzado.
2. **Pipelines de Redes Convolucionales Cuda:**
   Ejecutar librerías directas de CUDA de Nvidia, delegando las transferencias YOLO al hardware GPU esclavo del Host en producción.
3. **Distribución Multi-Workers Horizontal:**
   Migrar el nodo ASGI de desarrollo hacia Gunicorn como proxy local de balanceo (orquestando múltiples Hilos Worker en paralelo), permitiendo sostener hasta 15,000 conexiones transables en despliegues con Dockerización.

---
© 2026 GEOMAPS UX/AI TEAM. PLATAFORMA DE INTELIGENCIA TERRITORIAL.
