"""Sequencer Agent: ordena tracks por curva de energía (BPM) y transiciones armónicas (Camelot)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .analysis import analyze_song, harmonic_distance_camelot
from .config import settings
from .models import SongAnalysis


def analyze_tracks(paths: list[Path], sr: Optional[int] = None) -> list[tuple[Path, SongAnalysis]]:
    """Analiza BPM y Key de cada track. Devuelve lista (path, SongAnalysis)."""
    sr = sr or settings.default_sr
    result: list[tuple[Path, SongAnalysis]] = []
    for p in paths:
        if not p.exists() or not p.is_file():
            continue
        try:
            analysis = analyze_song(p, sr=sr)
            result.append((p, analysis))
        except Exception:
            continue
    return result


def sort_playlist(
    analyzed: list[tuple[Path, SongAnalysis]],
    energy_curve_ascending: bool = True,
) -> list[tuple[Path, SongAnalysis]]:
    """
    Ordena la lista: curva de energía (BPM ascendente por defecto) y transiciones armónicas.
    - Primario: BPM (ascendente = subida de energía).
    - Secundario: preferir siguiente track con menor distancia Camelot (greedy).
    """
    if len(analyzed) <= 1:
        return list(analyzed)

    # Orden inicial por BPM
    sorted_by_bpm = sorted(
        analyzed,
        key=lambda x: x[1].bpm,
        reverse=not energy_curve_ascending,
    )

    # Ajuste greedy por Camelot: para cada posición, elegir el siguiente que minimice harmonic_distance
    ordered: list[tuple[Path, SongAnalysis]] = [sorted_by_bpm[0]]
    remaining = list(sorted_by_bpm[1:])

    while remaining:
        last_analysis = ordered[-1][1]
        camelot_last = getattr(last_analysis, "key_camelot", None) or ""
        best_idx = 0
        best_dist = 10
        best_bpm_diff = 999.0
        for i, (_, a) in enumerate(remaining):
            camelot_a = getattr(a, "key_camelot", None) or ""
            dist = harmonic_distance_camelot(camelot_last, camelot_a)
            bpm_diff = abs(a.bpm - last_analysis.bpm)
            if dist < best_dist or (dist == best_dist and bpm_diff < best_bpm_diff):
                best_dist = dist
                best_bpm_diff = bpm_diff
                best_idx = i
        ordered.append(remaining.pop(best_idx))

    return ordered


def build_roadmap(
    ordered: list[tuple[Path, SongAnalysis]],
) -> list[tuple[Path, Path, SongAnalysis, SongAnalysis]]:
    """
    Hoja de ruta: Track B de la mezcla i es Track A de la mezcla i+1.
    Devuelve lista de (path_a, path_b, analysis_a, analysis_b) para cada transición.
    """
    roadmap: list[tuple[Path, Path, SongAnalysis, SongAnalysis]] = []
    for i in range(len(ordered) - 1):
        path_a, analysis_a = ordered[i]
        path_b, analysis_b = ordered[i + 1]
        roadmap.append((path_a, path_b, analysis_a, analysis_b))
    return roadmap
