"""Downloader: descarga samples por URL a carpeta temporal. Auto-cleanup después del render."""
from __future__ import annotations

import tempfile
import urllib.request
from pathlib import Path
from typing import List, Optional

OPUS_SAMPLES_DIR = "opus_samples"


def _temp_root() -> Path:
    return Path(tempfile.gettempdir()) / OPUS_SAMPLES_DIR


def download_to_temp(url: str, temp_dir: Optional[Path] = None) -> Path:
    """
    Descarga el archivo desde url a temp_dir (o /tmp/opus_samples).
    Devuelve el Path del archivo local. Crea temp_dir si no existe.
    """
    url = (url or "").strip()
    if not url.startswith("http"):
        raise ValueError("URL must start with http")
    temp_dir = temp_dir or _temp_root()
    temp_dir.mkdir(parents=True, exist_ok=True)
    # Nombre de archivo: último segmento de la URL o un hash corto
    name = url.split("/")[-1].split("?")[0] or "sample.wav"
    if not name.lower().endswith((".wav", ".mp3", ".flac", ".ogg", ".m4a")):
        name = name + ".wav"
    out_path = temp_dir / name
    req = urllib.request.Request(url, headers={"User-Agent": "OpusAI/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        out_path.write_bytes(resp.read())
    return out_path


def download_urls_to_temp(urls: List[str], temp_dir: Optional[Path] = None) -> tuple[List[Path], Path]:
    """
    Descarga varias URLs a un mismo temp_dir. Devuelve (lista de paths, temp_dir)
    para poder borrar temp_dir después del render.
    """
    import shutil
    temp_dir = temp_dir or Path(tempfile.mkdtemp(prefix=OPUS_SAMPLES_DIR + "_"))
    temp_dir.mkdir(parents=True, exist_ok=True)
    paths: List[Path] = []
    for i, url in enumerate(urls):
        if not url or not url.strip().startswith("http"):
            continue
        ext = Path(url.split("/")[-1].split("?")[0]).suffix or ".wav"
        name = f"cloud_{i}{ext}"
        out_path = temp_dir / name
        req = urllib.request.Request(url.strip(), headers={"User-Agent": "OpusAI/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            out_path.write_bytes(resp.read())
        paths.append(out_path)
    return paths, temp_dir


def cleanup_temp_dir(temp_dir: Path) -> None:
    """Borra el directorio temporal y su contenido."""
    if not temp_dir.exists():
        return
    try:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception:
        pass
