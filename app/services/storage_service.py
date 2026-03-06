import os
import uuid
from typing import List
from fastapi import UploadFile
from supabase import create_client, Client
from app.core.config import settings
from app.core.exceptions import FileUploadException

class StorageService:
    def __init__(self):
        self.supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
        self.buckets = {
            "images": "Imagen",
            "models": "Imagen3d",
            "shapefiles": "Shefile",
            "downloads": "Shefile"
        }

    async def upload_file(self, file: UploadFile, bucket_type: str) -> str:
        bucket_name = self.buckets.get(bucket_type)
        if not bucket_name:
            raise ValueError(f"Invalid bucket type: {bucket_type}")

        file_ext = os.path.splitext(file.filename)[1]
        unique_name = f"{uuid.uuid4()}{file_ext}"
        
        try:
            content = await file.read()
            # Validar tamaño (ej. 50MB para coincidir con el límite de Supabase mostrado)
            if len(content) > 50 * 1024 * 1024:
                raise FileUploadException("El archivo excede el tamaño máximo permitido (50MB)")

            # Subir a Supabase
            response = self.supabase.storage.from_(bucket_name).upload(
                path=unique_name,
                file=content,
                file_options={"content-type": file.content_type}
            )
            
            # Obtener URL pública
            public_url = self.supabase.storage.from_(bucket_name).get_public_url(unique_name)
            return public_url
        except Exception as e:
            raise FileUploadException(f"Error al subir archivo a Supabase: {str(e)}")

    async def delete_file(self, file_url: str, bucket_type: str):
        """
        Elimina un archivo de Supabase Storage basado en su URL pública.
        """
        bucket_name = self.buckets.get(bucket_type)
        if not bucket_name:
            raise ValueError(f"Tipo de bucket inválido: {bucket_type}")

        try:
            # Extraer el nombre del archivo de la URL
            # Ejemplo: https://.../storage/v1/object/public/bucket-name/filename.ext
            filename = file_url.split("/")[-1]
            
            self.supabase.storage.from_(bucket_name).remove([filename])
        except Exception as e:
            # No lanzamos excepción aquí para evitar que falle el flujo principal si el archivo no existe
            print(f"Error al eliminar archivo de Supabase: {str(e)}")

storage_service = StorageService()
