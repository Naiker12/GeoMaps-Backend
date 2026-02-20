# GeoMaps Backend

## Descripción
GeoMaps Backend es una API robusta diseñada para la gestión de datos geoespaciales, predios y proyectos. Este proyecto utiliza FastAPI como framework principal, siguiendo principios de Arquitectura Limpia (Clean Architecture) y Diseño Orientado al Dominio (DDD) para garantizar escalabilidad, mantenibilidad y desacoplamiento de componentes.

## Arquitectura del Proyecto
La aplicación está organizada en capas bien definidas para separar las responsabilidades:

### 1. Capa de API (api/)
Contiene los puntos de entrada (endpoints) de la aplicación. Se encarga de la validación de entrada, documentación automática con OpenAPI y el enrutamiento de peticiones hacia la capa de aplicación.

### 2. Capa de Aplicación (application/)
Orquesta el flujo de datos. Aquí se definen los casos de uso específicos de la aplicación y se coordina la interacción entre el dominio y la infraestructura.

### 3. Capa de Dominio (domain/)
Es el corazón del sistema.
- **Models**: Define las entidades y objetos de valor (Pydantic).
- **Services**: Contiene la lógica de negocio pura que no pertenece a una sola entidad.

### 4. Capa de Infraestructura (infrastructure/)
Maneja las implementaciones técnicas y externas:
- **Database**: Configuración de SQLAlchemy/PostgreSQL.
- **Repositories**: Implementación del acceso a datos, permitiendo cambiar la persistencia sin afectar al dominio.
- **Cache**: Manejo de estados temporales o performance (Redis).

### 5. Capa Core (core/)
Configuraciones globales del sistema, manejo de seguridad (JWT), hashing de contraseñas y dependencias transversales.

---

## Requisitos Previos
- Python 3.10 o superior.
- PostgreSQL con extensión PostGIS (recomendado para datos geográficos).
- Redis (opcional para cache).

## Instalación

1. **Clonar el repositorio**:
   ```bash
   git clone <url-del-repositorio>
   cd GeoMaps-Backend
   ```

2. **Crear y activar un entorno virtual**:
   En Windows:
   ```bash
   python -m venv venv
   .\venv\Scripts\activate
   ```
   En Linux/macOS:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Instalar dependencias**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configurar variables de entorno**:
   Crea un archivo `.env` en la raíz del proyecto basándote en las necesidades de `app/core/config.py`.

---

## Ejecución

Para iniciar el servidor de desarrollo, utiliza el siguiente comando:

```bash
uvicorn app.main:app --reload --port 8000
```

- La API estará disponible en: [http://localhost:8000](http://localhost:8000)
- La documentación interactiva (Swagger UI) en: [http://localhost:8000/docs](http://localhost:8000/docs)
- La documentación alternativa (ReDoc) en: [http://localhost:8000/redoc](http://localhost:8000/redoc)

## Tecnologías Principales
- **FastApi**: Framework web de alto rendimiento.
- **SQLAlchemy & Alembic**: ORM y gestión de migraciones de base de datos.
- **GeoAlchemy2 & Shapely**: Manejo de datos geométricos y geográficos.
- **Pydantic**: Validación de datos y gestión de configuraciones.
- **Python-Jose & Passlib**: Seguridad y autenticación.
