"""Metadatos de audio con librosa: BPM, duración y picos de energía."""
from pathlib import Path
from typing import Optional

import librosa
import numpy as np


def get_audio_metadata(
    file_path: Path,
    sr: Optional[int] = None,
    hop_length: int = 512,
    top_peaks: int = 30,
) -> dict:
    """
    Usa librosa para obtener BPM real, duración y tiempos (segundos) donde
    la amplitud es más alta (energy_peaks).

    Returns:
        dict con: bpm (float), duration (float), energy_peaks (list[float] segundos).
    """
    sr = sr or 44100
    y, _ = librosa.load(str(file_path), sr=sr, mono=True)
    duration = float(len(y) / sr)

    tempo, _ = librosa.beat.beat_track(y=y, sr=sr, hop_length=hop_length)
    try:
        bpm = float(tempo[0]) if hasattr(tempo, "__len__") and len(tempo) else float(tempo)
    except (IndexError, TypeError):
        bpm = 120.0
    bpm = max(60.0, min(200.0, bpm))

    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    if rms.size == 0:
        return {"bpm": bpm, "duration": duration, "energy_peaks": []}

    frame_times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)
    order = np.argsort(rms)[::-1]
    peak_times = []
    seen_sec = set()
    min_gap_sec = 2.0
    for i in order:
        t = float(frame_times[i])
        if t < 0 or t > duration:
            continue
        if any(abs(t - s) < min_gap_sec for s in seen_sec):
            continue
        peak_times.append(round(t, 2))
        seen_sec.add(t)
        if len(peak_times) >= top_peaks:
            break
    peak_times.sort()

    return {
        "bpm": round(bpm, 2),
        "duration": round(duration, 2),
        "energy_peaks": peak_times,
    }
