"""Librería de samples para overlays IA: percussion, instruments, vocals. BPM/Key compatibles."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .analysis import analyze_song, key_to_camelot
from .config import settings

SAMPLE_CATEGORIES = ("percussion", "instruments", "vocals")
_AUDIO_EXT = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}


def get_samples_dir() -> Path:
    """Directorio base: assets/samples (percussion, instruments, vocals dentro)."""
    return Path(settings.assets_samples_dir)


def _metadata_path(audio_path: Path) -> Path:
    """Sidecar JSON para cachear BPM/Key: mismo nombre + .json."""
    return audio_path.with_suffix(audio_path.suffix + ".json")


def get_sample_metadata(audio_path: Path, sr: Optional[int] = None) -> dict:
    """
    BPM y key_camelot de un sample. Lee sidecar .json si existe; si no, analiza y escribe cache.
    Returns dict con bpm, key_camelot, key, key_scale.
    """
    meta_path = _metadata_path(audio_path)
    if meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "bpm" in data and "key_camelot" in data:
                return data
        except Exception:
            pass
    try:
        analysis = analyze_song(audio_path, sr=sr or settings.default_sr)
        camelot = getattr(analysis, "key_camelot", None) or key_to_camelot(analysis.key, analysis.key_scale)
        data = {
            "bpm": round(analysis.bpm, 1),
            "key": analysis.key,
            "key_scale": analysis.key_scale,
            "key_camelot": camelot,
        }
        try:
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=0)
        except OSError:
            pass
        return data
    except Exception:
        return {"bpm": 120.0, "key": "C", "key_scale": "major", "key_camelot": "8A"}


def list_samples(category: str) -> list[Path]:
    """Lista archivos de audio en assets/samples/{category}."""
    if category not in SAMPLE_CATEGORIES:
        return []
    folder = get_samples_dir() / category
    if not folder.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(folder.iterdir()):
        if p.is_file() and p.suffix.lower() in _AUDIO_EXT:
            out.append(p)
    return out


def _camelot_distance(c1: str, c2: str) -> int:
    """Distancia en rueda Camelot (0 = mismo/relativo, 1 = vecino, 2+ = lejano)."""
    if not c1 or not c2:
        return 99
    c1, c2 = c1.strip().upper(), c2.strip().upper()
    try:
        n1, l1 = int(c1[:-1]), c1[-1]
        n2, l2 = int(c2[:-1]), c2[-1]
    except (ValueError, IndexError):
        return 99
    if n1 == n2:
        return 0
    d = abs(n1 - n2)
    d = min(d, 12 - d)
    return d


def get_compatible_samples(
    bpm: float,
    key_camelot: str,
    categories: list[str],
    bpm_tolerance: float = 5.0,
    max_camelot_distance: int = 1,
) -> list[tuple[Path, dict]]:
    """
    Samples compatibles con el BPM y la key de la mezcla actual.
    - BPM dentro de [bpm - bpm_tolerance, bpm + bpm_tolerance].
    - Key: misma o vecina en Camelot (distance <= max_camelot_distance).
    Returns list of (path, metadata) for use in overlay selection.
    """
    result: list[tuple[Path, dict]] = []
    bpm_min = max(1.0, bpm - bpm_tolerance)
    bpm_max = bpm + bpm_tolerance
    key_camelot = (key_camelot or "").strip().upper() or "8A"

    for cat in categories:
        if cat not in SAMPLE_CATEGORIES:
            continue
        for path in list_samples(cat):
            meta = get_sample_metadata(path)
            meta_bpm = float(meta.get("bpm", 120))
            meta_key = (meta.get("key_camelot") or "").strip().upper()
            if not (bpm_min <= meta_bpm <= bpm_max):
                continue
            dist = _camelot_distance(meta_key, key_camelot)
            if dist <= max_camelot_distance:
                result.append((path, {**meta, "category": cat}))
    return result
