"""Cloud index: samples por URL desde JSON (vocals / instruments). Compatible con el Sequencer."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_CLOUD_INDEX_PATH = Path(__file__).resolve().parent / "cloud_assets.json"


def load_cloud_assets() -> dict[str, list[dict[str, Any]]]:
    """
    Carga cloud_assets.json. Estructura: {"vocals": [...], "instruments": [...]}.
    Cada entrada tiene name, url, bpm, key.
    """
    if not _CLOUD_INDEX_PATH.exists():
        return {"vocals": [], "instruments": []}
    try:
        with open(_CLOUD_INDEX_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"vocals": [], "instruments": []}
    if not isinstance(data, dict):
        return {"vocals": [], "instruments": []}
    vocals = data.get("vocals")
    instruments = data.get("instruments")
    return {
        "vocals": vocals if isinstance(vocals, list) else [],
        "instruments": instruments if isinstance(instruments, list) else [],
    }


def get_cloud_compatible_samples(
    bpm: float,
    key_camelot: str,
    categories: list[str],
    bpm_tolerance: float = 5.0,
    max_camelot_distance: int = 1,
) -> list[dict[str, Any]]:
    """
    Devuelve la lista de samples del JSON (vocals + instruments) para las categorías pedidas.
    Filtra por BPM y key si se desea; por defecto devuelve todos los de la categoría.
    Returns list of dicts with name, url, bpm, key, category.
    """
    raw = load_cloud_assets()
    result: list[dict[str, Any]] = []
    bpm_min = max(1.0, bpm - bpm_tolerance)
    bpm_max = bpm + bpm_tolerance
    for cat in categories:
        cat = (cat or "").strip().lower()
        if cat not in ("vocals", "instruments"):
            continue
        entries = raw.get(cat, [])
        for e in entries:
            if not isinstance(e, dict) or not e.get("url"):
                continue
            meta_bpm = float(e.get("bpm", 120))
            if not (bpm_min <= meta_bpm <= bpm_max):
                continue
            result.append({**e, "category": cat})
    return result


def get_cloud_assets_flat() -> list[dict[str, Any]]:
    """Lista plana de todos los samples (vocals + instruments) para inyectar en el prompt."""
    raw = load_cloud_assets()
    out: list[dict[str, Any]] = []
    for cat, entries in [("vocals", raw.get("vocals", [])), ("instruments", raw.get("instruments", []))]:
        for e in (entries or []):
            if isinstance(e, dict) and e.get("url"):
                out.append({**e, "category": cat})
    return out
