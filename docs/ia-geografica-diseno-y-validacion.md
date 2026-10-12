# IA geográfica: implementación y validación

Revisión del 12 de octubre de 2026. El modelo interpreta la petición y selecciona herramientas; PostGIS calcula los resultados. El backend devuelve datos, gráfico compatible con el contrato existente y metadatos de cada análisis.

## Comportamiento implementado

- `analizar_capa_geografica`: conteos completos de geometrías elegibles, distribución por tipo y suma de áreas de polígonos en m². Permite bbox, polígono GeoJSON válido, proximidad de 1 a 50.000 metros o toda la capa explícita.
- Las consultas de zona usan intersección exacta, además del filtro de candidatos por envolvente. Proximidad usa `ST_DWithin` sobre geography; áreas usan `ST_Area` sobre geography.
- El contexto prioriza zona de conversación, extensión de conversación y finalmente viewport. Convierte Web Mercator a EPSG:4326 con pyproj; rechaza sistemas desconocidos y extensiones inválidas antes de iniciar chat o streaming.
- El polígono seleccionado sustituye el viewport para la nueva herramienta. El radio conserva su centro; toda la capa no hereda filtros del mapa.
- Capas ambiguas devuelven candidatos con ID. Valores espaciales, nombres y UUID son parámetros SQL. Se excluyen capas privadas.
- `analysis_results` incluye fuente, capa, alcance, CRS, radio, conteos y advertencias en ChatResponse, evento SSE `done` e historial.
- Se eliminan preguntas preliminares obligatorias para gráficos. El prompt permite barras automáticas y solicita aclaración cuando falta un dato necesario. Una consulta fallida no equivale a cero resultados.
- Chat y streaming comparten comprobación de propiedad de conversación antes de leer historial o resumen.

Ejemplos: «¿Cuántos parques intersectan la zona seleccionada?», «Analiza parques a 500 metros de estas coordenadas». La presentación incluye hallazgo, fuente/alcance y limitación relevante; los gráficos conservan `analytics_data` para consumidores existentes.

## Límites

La suma de áreas corresponde a polígonos completos: no recorta al área consultada ni elimina solapamientos y no representa porcentaje de cobertura. Conteos excluyen geometrías nulas, inválidas, con SRID distinto de 4326 o fuera de rango. Intersección incluye elementos que tocan el borde. No se deben inferir causalidad ni coordenadas inventadas.

Los filtros de atributos de contexto se comunican al modelo, pero la nueva herramienta no los aplica como predicados SQL. Sus métricas describen el alcance espacial y la capa, no un subconjunto filtrado por atributos. Los gráficos muestran el último gráfico; `analysis_results` conserva los metadatos de todos los análisis.

La consulta usa CTE MATERIALIZED (PostgreSQL 12 o posterior). Para grandes volúmenes hay que medir planes reales y considerar índice GiST sobre geography para proximidad; no se añadió una migración de índice sin evidencia del despliegue.

## Validación y siguiente paso

Suite completa: 151 pruebas aprobadas; compileall y git diff --check sin errores. La salida «storage unavailable» corresponde al caso de fallo simulado de almacenamiento.

`tests/test_ai_geography.py` cubre conversión real con pyproj, contexto, CRS inválido, unidades y parámetros SQL, capas ambiguas, selección por ID, polígonos válidos/inválidos, aislamiento radio/viewport, conversación ajena y múltiples análisis sin preguntas preliminares. DB y proveedor de IA están simulados: no acredita exactitud numérica de PostGIS, calidad del modelo real ni experiencia visual del frontend. No se modificó el frontend.

Validación de despliegue pendiente: dataset PostGIS conocido con polígonos solapados, huecos, bordes y distancias de referencia; comparar resultados y EXPLAIN ANALYZE. Luego, implementar cobertura por intersección/unión y agrupación por atributos con pruebas, y evaluar preguntas reproducibles del proveedor real.

Referencias primarias: [ST_DWithin](https://postgis.net/docs/manual-3.5/en/ST_DWithin.html), [ST_Intersects](https://postgis.net/docs/ST_Intersects.html), [ST_Area](https://postgis.net/docs/ST_Area.html), [ST_IsValid](https://postgis.net/docs/ST_IsValid.html).
