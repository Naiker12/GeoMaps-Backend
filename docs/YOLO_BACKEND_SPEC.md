# 🛠️ Especificación Técnica: Backend YOLOv8 para GeoMaps

Esta especificación detalla la implementación del motor de IA en el backend FastAPI, siguiendo patrones de Clean Architecture.

## 1. Nuevas Dependencias (`requirements.txt`)
Se deben añadir las siguientes librerías para habilitar el procesamiento de IA y visión computacional:
```text
ultralytics==8.3.0
opencv-python-headless==4.10.0.84
numpy==2.2.0
```

## 2. Servicio de IA (`app/services/ai_service.py`)

El servicio encapsula la lógica de inferencia y la transformación de coordenadas.

```python
import cv2
import numpy as np
from ultralytics import YOLO
from shapely.geometry import Polygon, mapping
from typing import List, Dict, Any

class AIService:
    def __init__(self, model_path: str = "yolov8n.pt"):
        self.model = YOLO(model_path)

    async def detect_and_georeference(
        self, 
        image_bytes: bytes, 
        bounds: Dict[str, float], 
        confidence: float = 0.25
    ) -> Dict[str, Any]:
        # 1. Decodificar imagen
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        h, w, _ = img.shape

        # 2. Inferencia YOLO
        results = self.model.predict(img, conf=confidence)
        
        features = []
        west, south, east, north = bounds['west'], bounds['south'], bounds['east'], bounds['north']
        
        # 3. Transformación Pixel -> Geo
        for result in results:
            for box in result.boxes:
                # Coordenadas en píxeles (x1, y1, x2, y2)
                coords = box.xyxy[0].cpu().numpy()
                x1, y1, x2, y2 = coords
                
                # Convertir a Lat/Lon
                def pixel_to_geo(px, py):
                    lon = west + (px / w) * (east - west)
                    lat = north - (py / h) * (north - south)
                    return (lon, lat)

                # Crear polígono (4 esquinas)
                p1 = pixel_to_geo(x1, y1)
                p2 = pixel_to_geo(x2, y1)
                p3 = pixel_to_geo(x2, y2)
                p4 = pixel_to_geo(x1, y2)
                
                poly = Polygon([p1, p2, p3, p4, p1])
                
                features.append({
                    "type": "Feature",
                    "geometry": mapping(poly),
                    "properties": {
                        "class": result.names[int(box.cls[0])],
                        "confidence": float(box.conf[0]),
                        "box_px": [float(x) for x in coords]
                    }
                })

        return {
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "count": len(features),
                "model": "YOLOv8n",
                "image_size": [w, h]
            }
        }
```

## 3. Router de API (`app/api/v1/detection_routes.py`)

```python
from fastapi import APIRouter, UploadFile, File, Form, Depends
from app.services.ai_service import AIService
from typing import Optional

router = APIRouter()

@router.post("/detect")
async def detect_objects(
    file: UploadFile = File(...),
    west: float = Form(...),
    south: float = Form(...),
    east: float = Form(...),
    north: float = Form(...),
    confidence: float = Form(0.25),
    ai_service: AIService = Depends(AIService)
):
    image_bytes = await file.read()
    bounds = {"west": west, "south": south, "east": east, "north": north}
    
    result = await ai_service.detect_and_georeference(image_bytes, bounds, confidence)
    return result
```

## 4. Consideraciones de Rendimiento
-   **Warm-up:** Cargar el modelo YOLO al inicio de la aplicación (en el `lifespan` de FastAPI) para evitar latencia en la primera petición.
-   **GPU vs CPU:** Si el servidor tiene GPU, YOLOv8 lo detectará automáticamente. Para servidores modestos, se recomienda usar la versión `.pt` más ligera (`yolov8n`).
-   **Escalabilidad:** Procesar detecciones en segundo plano (BackgroundTasks) si el área es muy grande, notificando vía WebSockets al finalizar.
