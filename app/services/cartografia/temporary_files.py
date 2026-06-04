"""Temporary-file lifecycle helpers for generated cartography exports."""

from __future__ import annotations

import asyncio
import os


async def cleanup_generated_file(path: str, delay_seconds: int = 60) -> None:
    await asyncio.sleep(delay_seconds)
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except PermissionError:
        # Windows can keep the file handle briefly after a streamed download.
        await asyncio.sleep(delay_seconds)
        try:
            os.unlink(path)
        except OSError:
            pass
