# 🔱 GeoMaps Backend

![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql)
![PostGIS](https://img.shields.io/badge/PostGIS-336699?style=for-the-badge&logo=postgis)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-D71F00?style=for-the-badge&logo=sqlalchemy)

**GeoMaps** es una plataforma backend de alto rendimiento diseñada para la gestión integral de proyectos inmobiliarios y datos geoespaciales. Construida sobre los cimientos de **FastAPI**, **PostgreSQL** y **PostGIS**, ofrece una infraestructura robusta para la visualización 3D, métricas financieras y control administrativo de predios.

---

## 🏗️ Arquitectura del Sistema

El proyecto implementa una **Arquitectura Limpia (Clean Architecture)** combinada con principios de **Diseño Orientado al Dominio (DDD)**, ahora potenciada con **procesamiento asíncrono** total.

- **`app/api`**: Puntos de entrada (REST Endpoints) asíncronos v1.
- **`app/application`**: Casos de uso asíncronos y orquestación de servicios.
- **`app/domain`**: Modelos lógicos, entidades Pydantic y lógica de negocio pura.
- **`app/infrastructure`**: Repositorios basados en `AsyncSession` y sincronización con Supabase.
- **`app/core`**: Seguridad JWT, configuraciones globales y gestión de archivos.

---

## 🚀 Funcionalidades Principales

### 📍 Gestión Geoespacial Avanzada
- **Motor Asíncrono**: Refactorización completa a `SQLAlchemy Async` para manejo masivo de peticiones concurrentes.
- **Soporte PostGIS**: Manejo complejo de geometrías, puntos y polígonos con GeoAlchemy2.
- **API de Capas (Layers)**: Endpoints dedicados para la obtención dinámica de archivos **Shapefile**, **XML** y **GeoJSON**.
- **Servidor de Features**: Conversión y entrega de datos geográficos en tiempo real para el visor del mapa.

### 📊 Inteligencia Inmobiliaria
- **Métricas de Proyecto**: Gestión de áreas, niveles, unidades y seguimiento progresivo.
- **Módulo Financiero**: Control multimoneda (COP, USD, EUR) de inversiones y precios unitarios.
- **Dashboard Admin**: Control total sobre la visibilidad de capas, prioridades y categorización dinámica.

### 🔐 Seguridad y Auth
- **Integración Supabase**: Sincronización transparente de usuarios y autenticación segura.
- **RBAC**: Control de acceso granular (Admin, Superadmin, Public).

### 🖼️ Recursos Multimedia y 3D
- Gestión centralizada de archivos fuente geográficos.
- Almacenamiento y servicio de modelados 3D para integración con ArcGIS.
- Configuración de estilos visuales (colores, opacidad) persistente en base de datos.

---

## 🛠️ Stack Tecnológico

- **Framework**: FastAPI (**Totalmente Asíncrono**)
- **ORM & DB**: SQLAlchemy 2.0 (Async) + PostgreSQL / PostGIS
- **Migraciones**: Alembic
- **Procesamiento Geo**: GeoAlchemy2, Shapely, Pydantic v2
- **Auth**: Supabase Auth Integration

---

## ⚙️ Configuración y Ejecución

### Requisitos Previos
- Python 3.10+
- PostgreSQL v14+ con extensión PostGIS instalada.

### Instalación Rápida

1. **Clonar e Instalar**:
   ```bash
   git clone <repo-url>
   cd GeoMaps-Backend
   python -m venv venv
   source venv/bin/activate  # En Windows: .\venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Variables de Entorno**:
   Configurar `.env` con las credenciales de base de datos asíncrona (`postgresql+asyncpg://...`) y tokens de Supabase.

3. **Ejecutar Servidor**:
   ```bash
   uvicorn app.main:app --reload
   ```

---

## 📖 Documentación Automática

- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

Developed with ❤️ for **GeoMaps** ecosystem.
Plataforma de Alto Rendimiento para Inteligencia Territorial.
