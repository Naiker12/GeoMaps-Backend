# Pruebas del backend

Desde la raíz, con Python 3.12 y las dependencias de requirements.txt instaladas:

```powershell
python -m unittest discover -s tests -v
```

La suite usa unittest y mocks para consultas, cuotas y decodificación de tokens. Incluye peticiones HTTP con dependencias reales de FastAPI. No conecta con PostgreSQL ni Supabase, ni aplica migraciones. Las pruebas RPM arrancan un Redis aislado si `redis-server` está disponible; lo cierran al terminar y no utilizan el Redis de la aplicación. La configuración ficticia se centraliza en `backend_test_environment.py` y no escribe archivos .env.

Casos: cuentas desactivadas mediante JWT/API key, credenciales opcionales, fallos de base de datos, fallback de identidad, vencimiento de llaves, cuotas, timestamps UTC, perfil mediante API key, campos administrativos y orígenes locales exactos.

Validación actual del 12 de octubre de 2026: las 137 pruebas pasaron usando el entorno local `venv` con Python 3.13.12, incluidas tres integraciones con Redis 5.0.14.1 aislado y un upsert concurrente ejecutado en SQLite. El bloqueo de Pydantic observado en el entorno temporal anterior no se reprodujo en este entorno.

## Búsqueda GIS

```powershell
python -m unittest discover -s tests -p test_search.py -v
```

Estas seis pruebas pasaron tras retirar proyectos. Verifican resultados GIS, metadatos de navegación, distancias, consultas vacías, sugerencias y registro de visualizaciones. Una referencia histórica de proyectos no ejecuta escrituras. Usan una sesión simulada y no conectan con la base de datos.

## Almacenamiento

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -p test_storage.py -v
```

Cinco pruebas verifican lectura limitada en cargas mayores a 50 MB, aceptación del tamaño máximo, metadatos de carga, conservación de la causa de errores y ejecución de operaciones síncronas en hilos de trabajo. Supabase se simula; no se suben ni eliminan archivos reales.

## Análisis y carga de descargas

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -p test_download_storage.py -v
```

Once pruebas cubren CSV con saltos de línea entre comillas, GeoJSON con geometrías nulas o malformadas, JSON inválido, archivos vacíos, límite de lectura, restauración del cursor, procesamiento en hilos de trabajo y limpieza de temporales ZIP. Incluyen peticiones HTTP de carga válida y rechazo por tamaño (413), además del rechazo de nombres ausentes. La lectura geoespacial ZIP se simula: no verifica un archivo comprimido real contra GDAL.

## API keys, identidad y buenas prácticas

`test_api_key_rate_limit.py` comprueba validación de límites positivos, rechazo 429 con Retry-After y fallo Redis 503. Si encuentra `redis-server`, arranca un proceso local sin persistencia y prueba 30 peticiones concurrentes, vencimiento de ventana y aislamiento de llaves. Sin el ejecutable, esas tres integraciones se omiten explícitamente.

`test_backend_practices.py` verifica compatibilidad de imports ORM, consultas de cuotas parametrizadas, límites coherentes, UTC en revocación, mensajes de error sin detalles internos y CORS restringido. `test_auth_service.py` cubre creación con rol USER, identidades inválidas, cuentas inactivas, rollback, comprobación de contraseña fuera del event loop y transacciones de perfil sin duplicar. La suite de autenticación también valida sesiones con sid, y búsqueda comprueba coordenadas, límites y el parámetro entero de feature.

`test_search_access.py` prueba propagación de permisos HTTP y ejecuta SQL portable de sugerencias/visualizaciones contra SQLite en memoria: sin autenticación no muestra nombres privados ni actualiza sus visualizaciones. No ejecuta búsquedas espaciales PostGIS. `test_layer_files.py` verifica lectura limitada, procesamiento fuera del event loop, restauración del cursor y limpieza de ZIP de capas.

`test_layer_access.py` verifica la política pública en siete rutas de lectura, filtros SQL de categorías/GeoJSON/propiedades/detalles/campos, respuestas 404 para features inaccesibles, IDs enteros y propagación de errores de base de datos. Estas consultas ORM se inspeccionan con sesión simulada; no sustituyen integración PostGIS.

`test_api_key_accounting.py` cubre reserva previa con FOR UPDATE por usuario, finalización idempotente, liberación por respuesta fallida, fecha de admisión en estadísticas, middleware ante 429/excepciones/timeout y cierre de sesión de logging. Ejecuta la expresión de upsert sobre SQLite con 30 escrituras concurrentes y verifica que conserva todos los incrementos. No prueba el bloqueo de filas en PostgreSQL; falta esa integración real. Autenticación incluye dos casos adicionales de admisión concurrente rechazada y de resolución repetida sin doble reserva.

`test_jwt_security.py` firma tokens HS256/ES256/RS256 con llaves de prueba y verifica claims, secreto literal y caché JWKS simulada. `test_report_security.py` cubre propiedad de estado/descarga, sesión independiente del trabajo y render en hilos; el PDF usa bytes ficticios y no valida maquetación ni Typst real. `test_ogc_proxy.py` simula streaming HTTP para comprobar límites y errores sin tráfico externo. Las pruebas administrativas comprueban identidad User canónica y ausencia de elevación implícita de privilegios.

`test_resource_ownership.py` verifica política propietario/admin y rechazo antes de efectos en DB/storage. `test_layer_transactions.py` cubre reemplazo transaccional, reserva de bloqueo de capa, compensación del archivo nuevo, no eliminación de archivos ante fallos DB y WKT parametrizado. `test_spatial_queries.py` comprueba campos JSON parametrizados, bbox/límites válidos, valores numéricos con signo y propagación de errores DB. `test_download_publication.py` valida publicación del catálogo y orden de eliminación DB/storage. DB y storage se simulan; faltan integraciones PostgreSQL/PostGIS reales para este lote.
