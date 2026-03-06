# GEOMAPS - Backend API

**GEOMAPS Backend** es el motor de alto rendimiento que sustenta la plataforma GEOMAPS, proporcionando una API robusta para la gestión, procesamiento y visualización de datos geoespaciales complejos. Diseñado bajo principios de escalabilidad y mantenibilidad, este backend permite realizar consultas espaciales avanzadas, gestionar autenticación segura y servir metadatos territoriales en tiempo real.

Este repositorio constituye el núcleo lógico del ecosistema **GEOMAPS**, integrando potentes herramientas de análisis geográfico con una arquitectura backend moderna.

---

##  Características Principales

| Característica | Descripción |
| :--- | :--- |
| **Consultas Espaciales** | Soporte nativo para operaciones geométricas complejas (intersecciones, buffers, distancias) mediante PostGIS y GeoAlchemy2. |
| **API RESTful de Alta Velocidad** | Implementación asíncrona con **FastAPI** para una baja latencia y alta concurrencia. |
| **Integración con Supabase** | Sincronización de autenticación y persistencia de datos en tiempo real. |
| **Procesamiento de Datos** | Uso de **GeoPandas** y **Shapely** para manipulación avanzada de capas vectoriales y sistemas de coordenadas. |
| **Arquitectura de Repositorios** | Abstracción de la capa de datos para facilitar el intercambio de motores de persistencia y mejorar la testabilidad. |

---

##  Arquitectura Tecnológica

El stack ha sido seleccionado para ofrecer máxima precisión geográfica y eficiencia en el manejo de grandes volúmenes de datos:

| Tecnología | Rol en el Proyecto |
| :--- | :--- |
| **Python 3.10+** | Lenguaje núcleo por su madurez en el ecosistema de ciencia de datos y SIG. |
| **FastAPI** | Framework web moderno para la construcción de APIs con validación automática (Pydantic). |
| **PostgreSQL + PostGIS** | Base de datos relacional con extensión espacial para almacenamiento de geometrías. |
| **SQLAlchemy 2.0** | ORM avanzado para una gestión de base de datos eficiente y segura. |
| **GeoAlchemy2** | Extensión de SQLAlchemy para el manejo transparente de tipos espaciales. |
| **Alembic** | Sistema de migraciones para el control de versiones del esquema de la base de datos. |
| **Supabase** | Backend-as-a-Service para gestión de usuarios y almacenamiento de archivos. |
| **Redis** | Capa de caché (opcional) para optimizar consultas frecuentes. |

---

##  Análisis de la Arquitectura (Clean Architecture)

La arquitectura de **GEOMAPS Backend** sigue un patrón de capas desacopladas, lo que permite que la lógica de negocio permanezca aislada de los detalles de implementación (como la base de datos o APIs externas).

### 1. Capa de API y Rutas (`app/api`)
Es el punto de entrada de las solicitudes. Define los endpoints, maneja el versionamiento (v1) y valida los datos de entrada/salida utilizando **Pydantic Schemas**.
- **Auth Sync:** Sincronización transparente con los tokens JWT de Supabase.
- **Layers & Search:** Endpoints optimizados para la recuperación de capas y búsquedas territoriales por código catastral o coordenadas.

### 2. Capa de Dominio y Entidades (`app/domain`)
Contiene el corazón del negocio. Aquí se definen los modelos de dominio que representan las entidades del territorio y las reglas que las gobiernan, independientemente de cómo se guarden en la base de datos.

### 3. Capa de Repositorios (`app/repositories`)
Implementa el **Repository Pattern**. Esta capa abstrae todas las operaciones de lectura y escritura.
- **Consultas PostGIS:** Las consultas de proximidad y análisis espacial se encapsulan aquí para mantener las rutas de la API limpias.
- **Eficiencia:** Implementación de índices espaciales y optimización de queries SQL.

### 4. Capa de Infraestructura (`app/infrastructure`)
Maneja las comunicaciones externas:
- **Database Client:** Gestión de sesiones y conexiones mediante SQLAlchemy.
- **Supabase Integration:** Clientes para interacción con storage y auth externo.

---

##  Estructura del Proyecto

```bash
app/
├── api/            # Rutas de la API, endpoints (v1) y dependencias.
├── application/    # Casos de uso y lógica de aplicación.
├── core/           # Configuración global, seguridad, logging y excepciones.
├── db/             # Sesión de base de datos y configuración del motor.
├── domain/         # Modelos de dominio y lógica de negocio pura.
├── infrastructure/ # Adaptadores externos (Supabase, Mail, etc.).
├── repositories/   # Implementación de persistencia de datos (SQLAlchemy).
├── schemas/        # Modelos Pydantic para validación y serialización.
└── services/       # Servicios transversales de lógica compleja.
```

---

##  Instalación y Configuración

### Prerrequisitos
- **Python 3.10+**
- **PostgreSQL** con extensión **PostGIS**.
- **Virtualenv** o similar.

### Pasos para el levantamiento local

1. **Clonar el repositorio:**
   ```bash
   git clone https://github.com/Naiker12/GeoMaps-Backend.git
   cd geomaps-backend
   ```

2. **Crear e hidratar el entorno virtual:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # En Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configurar variables de entorno:**
   Copia el archivo `.env.example` (si existe) o crea un `.env` con las siguientes claves:
   ```env
   DATABASE_URL=postgresql+psycopg://user:password@localhost/geomaps_db
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_KEY=your-anon-key
   SECRET_KEY=your-secret-key
   ```

4. **Ejecutar migraciones:**
   ```bash
   alembic upgrade head
   ```

5. **Iniciar el servidor de desarrollo:**
   ```bash
   uvicorn app.main:app --reload
   ```
   La API estará documentada y lista en `http://localhost:8000/docs`.

---

##  Comandos Útiles

- **Crear nueva migración:** `alembic revision --autogenerate -m "descripcion"`
- **Ejecutar tests:** `pytest`
- **Linting:** `flake8 app`

---
