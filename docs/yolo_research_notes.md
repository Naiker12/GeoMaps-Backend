# 🔬 Investigación y Bitácora: Integración YOLOv8 en GeoMaps

He completado la integración inicial del motor de detección de objetos en el backend, siguiendo las mejores prácticas recomendadas por el equipo de **Ultralytics**. Aquí detallo los hallazgos y decisiones técnicas tomadas.

---

## 1. Carga Eficiente de Modelos (Lifespan Mode)
Al investigar el repositorio de **Ultralytics**, se confirma que la carga del modelo (`YOLO("yolov8n.pt")`) es una operación pesada que no debe ocurrir dentro de una petición HTTP.

> [!IMPORTANT]
> He implementado el patrón **FastAPI Lifespan**. El modelo se carga **una sola vez** al arrancar el servidor y se guarda en un diccionario global `ml_models`. Esto reduce el tiempo de respuesta de segundos a milisegundos.

---

## 2. Lógica de Georreferenciación (Píxel → Geo)
Dado que las imágenes satelitales son representaciones planas de la Tierra, hemos aplicado una transformación de interpolación lineal entre los límites del mapa (Bounding Box) y la matriz de la imagen.

```python
def pixel_to_geo(px, py, width, height, west, east, north, south):
    lon = west + (px / width) * (east - west)
    lat = north - (py / height) * (north - south)
    return (lon, lat)
```

Cada "Bounding Box" detectado por YOLO se convierte automáticamente en un **Polígono GeoJSON**, permitiendo que GeoMaps lo renderice directamente como una capa espacial nativa.

---

## 3. Best Practices de Ultralytics Aplicadas
-   **Device Agnostic:** El motor detecta automáticamente si hay una GPU NVIDIA (CUDA) disponible o si debe usar la CPU.
-   **Nano Weights (`yolov8n`):** He configurado el uso del modelo "Nano". Es la versión más rápida y optimizada para despliegues web, manteniendo un balance excelente entre velocidad y precisión para objetos grandes como casas o piscinas.
-   **NMS (Non-Maximum Suppression):** Se utiliza la lógica interna de YOLO para evitar detecciones duplicadas sobre el mismo objeto.

---

## 4. Próxima Fase: Optimización con SAHI
Si planeamos analizar áreas satelitales muy grandes con objetos muy pequeños (como paneles solares o botes), la investigación sugiere usar **SAHI (Slicing Aided Hyper Inference)**.

**¿Cómo funciona?**
SAHI divide la imagen en pequeñas "rebanadas" (slices), ejecuta YOLO en cada una y luego une los resultados. Esto evita que los objetos pequeños se pierdan al redimensionar la imagen para la red neuronal.

---

> [!TIP]
> Puedes probar el nuevo endpoint enviando un POST a `/api/v1/detection/detect` con una captura de pantalla del mapa y los límites correspondientes.
