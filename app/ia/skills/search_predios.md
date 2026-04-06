# Skill: search_predios

## Qué hace
Busca predios (terrenos, lotes, propiedades) en la base de datos catastral
de GeoMaps dentro del área visible del mapa o por criterio de búsqueda.

## Cuándo usarlo
Úsalo cuando el usuario pregunte por:
- "predios en esta zona"
- "qué lotes hay aquí"
- "dime las propiedades de este sector"
- "busca el predio con matrícula X"
- cualquier pregunta sobre terrenos, lotes o propiedades inmobiliarias

## Parámetros requeridos
- bbox: [xmin, ymin, xmax, ymax] — área actual del mapa (siempre disponible)
- query: string — término de búsqueda opcional (matrícula, propietario)
- limit: int — máximo de resultados (default: 20)

## Formato de respuesta esperado
La tool devuelve una lista de predios. Preséntalos al usuario en una tabla Markdown clara con matrícula, propietario y área.
