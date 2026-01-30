"""Scanner de assets: instrumentos y vocales para el Sampler (Opus Quad)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import settings

_AUDIO_EXT = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}
_CATEGORIES = ("instruments", "vocals")


def scan_assets() -> dict[str, Any]:
    """
    Escanea assets/samples/instruments y assets/samples/vocals.
    Devuelve un dict tipo JSON con listas de nombres de archivo por categoría.
    Uso: inyección en el prompt del LLM (Productor Opus Quad).
    """
    base = Path(settings.assets_samples_dir)
    out: dict[str, list[str]] = {"instruments": [], "vocals": []}
    for cat in _CATEGORIES:
        folder = base / cat
        if not folder.is_dir():
            continue
        for p in sorted(folder.iterdir()):
            if p.is_file() and p.suffix.lower() in _AUDIO_EXT:
                out[cat].append(p.name)
    return out


def scan_assets_json() -> str:
    """Mismo que scan_assets() pero devuelve string JSON."""
    return json.dumps(scan_assets(), ensure_ascii=False)
