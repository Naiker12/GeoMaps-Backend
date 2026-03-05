# 🔱 GeoMaps Backend: Motor de Inteligencia Territorial

![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql)
![PostGIS](https://img.shields.io/badge/PostGIS-336699?style=for-the-badge&logo=postgis)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-D71F00?style=for-the-badge&logo=sqlalchemy)
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)

**GeoMaps Backend** es el núcleo de procesamiento de alto rendimiento para el sistema MIDAS. Diseñado para gestionar datos geoespaciales masivos, integrarlos con métricas inmobiliarias y servirlos de manera eficiente a través de una API REST totalmente asíncrona.

---

## 🚀 Flujos del Sistema (Cómo Funciona cada Proceso)

### 🔐 1. Flujo de Autenticación y Seguridad (Supabase Sync)
- **Proceso:** El backend se sincroniza con **Supabase Auth**. Cuando un usuario se registra o inicia sesión, el backend valida el JWT y gestiona los permisos mediante **RBAC** (Role-Based Access Control).
- **Implementación:** Se utiliza un middleware de seguridad y decoradores de FastAPI para proteger rutas de administración y portales privados.

### 📍 2. Flujo de Gestión Geoespacial (Layers)
- **Creación:** Se registran capas (Layers) con metadatos (categoría, visibilidad, fuente).
- **Ingesta Masiva:** Implementamos un sistema de **Bulk Insert** en `LayerRepository` que procesa miles de geometrías simultáneamente convirtiendo formatos WKT a objetos PostGIS mediante `ST_GeomFromText`.
- **Servicio GeoJSON:** El motor extrae las geometrías de la base de datos y las transforma en tiempo real a objetos **GeoJSON (FeatureCollection)** utilizando funciones nativas de PostGIS como `ST_AsGeoJSON`.

### 🔍 3. Flujo de Búsqueda Espacial
- **Proceso:** Permite localizar predios o características geográficas basadas en coordenadas o filtros de propiedades.
- **Tecnología:** Utiliza los índices espaciales de **PostGIS** para realizar consultas ultra rápidas sobre millones de registros.

### 📊 4. Flujo de Estadísticas Dinámicas
- **Proceso:** Recopila propiedades de múltiples capas para generar métricas financieras y de área.
- **Mecanismo:** Consultas optimizadas que solo extraen el campo `properties` (JSONB) para alimentar gráficos y tableros de control en el frontend.

---

## 🛠️ Stack Tecnológico y Librerías

Para lograr este rendimiento, hemos seleccionado las mejores herramientas del ecosistema Python:

| Librería | Función Principal | Por qué se usó |
| :--- | :--- | :--- |
| **FastAPI** | Framework Web | Velocidad extrema y soporte nativo para `async`/`await`. |
| **SQLAlchemy 2.0** | ORM Asíncrono | Manejo robusto de la base de datos con tipado fuerte y sesiones asíncronas. |
| **GeoAlchemy2** | Extensión Espacial | Puente perfecto entre SQLAlchemy y PostGIS para tipos de datos geométricos. |
| **PostGIS** | Base de Datos Espacial | El estándar de la industria para almacenamiento y análisis geográfico. |
| **GeoPandas & Shapely** | Procesamiento GIS | Manipulación de datos vectoriales y validación de geometrías en el backend. |
| **Pydantic v2** | Validación de Datos | Garantiza que cada entrada y salida de la API cumpla con el esquema definido. |
| **Alembic** | Migraciones | Control de versiones para el esquema de la base de datos. |

---

## 🏗️ Implementación y Arquitectura (Cómo se hizo)

El backend sigue una **Arquitectura Limpia (Clean Architecture)** con patrones **DDD (Domain-Driven Design)** para asegurar la escalabilidad:

1.  **Patrón Repositorio:** Centralizamos el acceso a datos en `repositories/`. Por ejemplo, `LayerRepository` encapsula toda la complejidad de las consultas SQL y transformaciones GIS.
2.  **Inyección de Dependencias:** Usamos el sistema de dependencias de FastAPI para gestionar sesiones de base de datos (`AsyncSession`) y servicios de forma desacoplada.
3.  **Procesamiento Asíncrono:** Todo el I/O (Base de datos, Redis, API Externas) se maneja con `asyncio`, permitiendo que el servidor maneje cientos de peticiones concurrentes sin bloquearse.
4.  **Manejo de Errores Global:** Implementamos `MIDASException` para capturar errores de lógica de negocio y devolver respuestas estandarizadas al frontend.

---

## ⚙️ Configuración y Ejecución

### Instalación en Desarrollo

1.  **Entorno Virtual**:
    ```bash
    python -m venv venv
    .\venv\Scripts\activate  # Windows
    source venv/bin/activate  # Linux/Mac
    ```
2.  **Dependencias**:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Variables de Entorno**:
    Crea un archivo `.env` basado en la configuración del servidor (Database URL, Supabase Keys, etc).
4.  **Ejecución**:
    ```bash
    uvicorn app.main:app --reload --port 8000
    ```

---

## 📖 Documentación

Accede a la documentación interactiva una vez el servidor esté corriendo:
- **Swagger**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

---
Desarrollado con precisión técnica para el ecosistema **MIDAS / GeoMaps**.
