"""Estructura del track: BPM, duración y segmentos de energía (amplitude/onset) para contexto del LLM."""
from pathlib import Path
from typing import Any, Optional

import librosa
import numpy as np


def analyze_track_structure(
    path: Path,
    sr: Optional[int] = None,
    hop_length: int = 512,
    segment_sec: float = 4.0,
) -> dict[str, Any]:
    """
    Carga el track con librosa y devuelve bpm, duration y una lista de segments
    basada en amplitud (RMS) y onset para puntos de alta/baja energía.

    Returns:
        dict con: bpm, duration_sec, segments (list of {start_sec, end_sec, energy_level}).
    """
    sr = sr or 44100
    y, _ = librosa.load(path, sr=sr, mono=True)
    duration_sec = float(len(y) / sr)

    # BPM
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr, hop_length=hop_length)
    try:
        bpm = float(tempo[0]) if hasattr(tempo, "__len__") and len(tempo) else float(tempo)
    except (IndexError, TypeError):
        bpm = 120.0
    bpm = max(60.0, min(200.0, bpm))

    # RMS por frame (energía)
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    # Onset strength para fronteras rítmicas
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)

    n_frames = len(rms)
    if n_frames == 0:
        return {
            "bpm": bpm,
            "duration_sec": duration_sec,
            "segments": [],
        }

    frame_duration = hop_length / sr
    max_rms = np.max(rms) if np.max(rms) > 0 else 1.0
    rms_norm = rms / max_rms

    # Umbrales para high / low / mid (terciles)
    low_q, mid_q = np.percentile(rms_norm, 33), np.percentile(rms_norm, 66)

    # Segmentar en ventanas de ~segment_sec segundos y etiquetar energía
    n_seg = max(1, int(duration_sec / segment_sec))
    seg_len_frames = n_frames // n_seg
    segments: list[dict[str, Any]] = []

    for i in range(n_seg):
        start_f = i * seg_len_frames
        end_f = (i + 1) * seg_len_frames if i < n_seg - 1 else n_frames
        chunk = rms_norm[start_f:end_f]
        mean_energy = float(np.mean(chunk))
        if mean_energy <= low_q:
            energy_level = "low"
        elif mean_energy >= mid_q:
            energy_level = "high"
        else:
            energy_level = "mid"
        start_sec = start_f * frame_duration
        end_sec = end_f * frame_duration
        segments.append({
            "start_sec": round(start_sec, 2),
            "end_sec": round(end_sec, 2),
            "energy_level": energy_level,
        })

    return {
        "bpm": bpm,
        "duration_sec": round(duration_sec, 2),
        "segments": segments,
    }
