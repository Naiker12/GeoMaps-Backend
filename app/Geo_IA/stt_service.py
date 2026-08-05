"""Speech-to-text service for chat voice fallback."""

from __future__ import annotations

import asyncio
from typing import Optional

from google import genai
from google.genai import types

from app.shared.core.config import settings


class STTService:
    """Transcribes short browser recordings using the configured provider."""

    async def transcribe(
        self,
        audio_bytes: bytes,
        language: str = "es-CO",
        mime_type: Optional[str] = None,
    ) -> str:
        if not audio_bytes:
            return ""

        provider = (settings.STT_PROVIDER or "gemini").lower()
        if provider != "gemini":
            raise ValueError(f"Proveedor STT no soportado: {settings.STT_PROVIDER}")

        return await asyncio.to_thread(
            self._transcribe_gemini,
            audio_bytes,
            language,
            mime_type or "audio/webm",
        )

    def _transcribe_gemini(self, audio_bytes: bytes, language: str, mime_type: str) -> str:
        if not settings.GOOGLE_API:
            raise RuntimeError("GOOGLE_API no esta configurado para transcripcion de audio.")

        client = genai.Client(api_key=settings.GOOGLE_API, http_options={"api_version": "v1beta"})
        prompt = (
            "Transcribe con puntuacion el siguiente audio en espanol. "
            f"Idioma esperado: {language}. Responde solo el texto transcrito."
        )
        response = client.models.generate_content(
            model=settings.STT_MODEL,
            contents=[
                prompt,
                types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
            ],
        )
        return (response.text or "").strip()


stt_service = STTService()