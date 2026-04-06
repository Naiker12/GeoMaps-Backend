# Skill: analyze_zone

## Qué hace
Genera un resumen estadístico de todos los elementos dentro del área
visible del mapa (BBox actual).

## Cuándo usarlo
Cuando el usuario pida:
- "analiza esta zona"
- "qué hay en el área visible"
- "resumen de esta zona"
- analiza esta zona
- qué hay en el área visible
- resumen de esta zona
- estadísticas del sector

## Parámetros requeridos
- bbox: [xmin, ymin, xmax, ymax]
- layers: lista de capas activas del usuario

## Formato de respuesta esperado
La tool devuelve estadísticas del sector. Explícalas al usuario usando tablas Markdown o listas enfocadas en la densidad de elementos por capa.
