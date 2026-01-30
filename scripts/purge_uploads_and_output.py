#!/usr/bin/env python3
"""
Purga única: elimina archivos viejos en backend/uploads/ y backend/output/ si existen
(legacy; el backend ya no escribe ahí, solo usa directorios temporales por sesión).

Uso (desde la raíz del proyecto, con venv activado):
  python scripts/purge_uploads_and_output.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Permitir importar backend.app (ejecutar desde raíz del proyecto)
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.app.config import settings

EXTENSIONS = (".mp3", ".wav", ".txt")

# Rutas legacy: el backend ya no las usa; solo para purgar datos viejos
UPLOADS_LEGACY = settings.base_dir / "uploads"
OUTPUT_LEGACY = settings.base_dir / "output"


def purge_dir(directory: Path) -> int:
    """Elimina todos los archivos con extensión en EXTENSIONS bajo directory. Devuelve cantidad eliminada."""
    if not directory.exists():
        return 0
    removed = 0
    for ext in EXTENSIONS:
        for f in directory.rglob(f"*{ext}"):
            if f.is_file():
                try:
                    f.unlink()
                    removed += 1
                    print(f"  Eliminado: {f}")
                except OSError as e:
                    print(f"  Error eliminando {f}: {e}", file=sys.stderr)
    return removed


def main() -> int:
    print("Purga legacy: uploads/ y output/ (solo .mp3, .wav, .txt); el backend usa solo sesiones temporales.")
    print(f"  uploads: {UPLOADS_LEGACY}")
    print(f"  output:  {OUTPUT_LEGACY}")
    total = 0
    total += purge_dir(UPLOADS_LEGACY)
    total += purge_dir(OUTPUT_LEGACY)
    print(f"Total archivos eliminados: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
