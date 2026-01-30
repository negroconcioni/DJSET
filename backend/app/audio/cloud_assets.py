"""Cloud index: samples por URL (category, bpm, key). Compatible con el Sequencer."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_CLOUD_INDEX_PATH = Path(__file__).resolve().parent / "cloud_assets.json"
_CATEGORIES = ("percussion", "instruments", "vocals")


def _camelot_distance(c1: str, c2: str) -> int:
    if not c1 or not c2:
        return 99
    c1, c2 = c1.strip().upper(), c2.strip().upper()
    try:
        n1 = int(c1[:-1])
        n2 = int(c2[:-1])
    except (ValueError, IndexError):
        return 99
    if n1 == n2:
        return 0
    d = abs(n1 - n2)
    return min(d, 12 - d)


def load_cloud_assets() -> list[dict[str, Any]]:
    """Carga cloud_assets.json. Devuelve lista de dicts con url, category, bpm, key, key_camelot."""
    if not _CLOUD_INDEX_PATH.exists():
        return []
    try:
        with open(_CLOUD_INDEX_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def get_cloud_compatible_samples(
    bpm: float,
    key_camelot: str,
    categories: list[str],
    bpm_tolerance: float = 5.0,
    max_camelot_distance: int = 1,
) -> list[dict[str, Any]]:
    """
    Samples de cloud (URLs) compatibles con BPM y key del set.
    Returns list of dicts with url, category, bpm, key, key_camelot.
    """
    key_camelot = (key_camelot or "").strip().upper() or "8A"
    bpm_min = max(1.0, bpm - bpm_tolerance)
    bpm_max = bpm + bpm_tolerance
    result: list[dict[str, Any]] = []
    for entry in load_cloud_assets():
        cat = (entry.get("category") or "").strip().lower()
        if cat not in _CATEGORIES or cat not in categories:
            continue
        meta_bpm = float(entry.get("bpm", 120))
        if not (bpm_min <= meta_bpm <= bpm_max):
            continue
        meta_key = (entry.get("key_camelot") or entry.get("key") or "").strip().upper() or "8A"
        if isinstance(meta_key, str) and len(meta_key) > 2:
            meta_key = meta_key[:2]
        dist = _camelot_distance(meta_key, key_camelot)
        if dist <= max_camelot_distance and entry.get("url"):
            result.append({**entry, "category": cat})
    return result
