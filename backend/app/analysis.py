"""Musical analysis: BPM, key, beats, energy. Uses librosa and Essentia."""
from pathlib import Path
from typing import Optional

import librosa
import numpy as np

from .models import SongAnalysis


def _key_essentia(path: Path) -> tuple[str, str]:
    """Detect key using Essentia KeyExtractor. Returns (key_name, scale)."""
    try:
        import essentia.standard as es
        loader = es.MonoLoader(filename=str(path))
        audio = loader()
        key_extractor = es.KeyExtractor()
        key, scale, strength = key_extractor(audio)
        key_name = key or "C"
        scale_name = (scale or "major").lower()
        return key_name, scale_name
    except Exception:
        return "C", "major"


def _bpm_librosa(y: np.ndarray, sr: int) -> float:
    """Estimate BPM with librosa."""
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    if hasattr(tempo, "__len__"):
        tempo = float(tempo[0]) if len(tempo) else 120.0
    return float(np.clip(tempo, 60, 200))


def _beats_librosa(y: np.ndarray, sr: int) -> list[float]:
    """Get beat times in seconds."""
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    return beat_times.tolist()


def _energy_librosa(y: np.ndarray, sr: int, hop_length: int = 512) -> float:
    """Overall energy 0-1: RMS normalized by max observed."""
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    if rms.size == 0:
        return 0.5
    max_rms = np.max(rms)
    if max_rms <= 0:
        return 0.5
    mean_rms = np.mean(rms)
    return float(np.clip(mean_rms / max_rms, 0, 1))


def analyze_song(path: Path, sr: Optional[int] = None) -> SongAnalysis:
    """
    Analyze one audio file: BPM, key, beats, energy.
    Uses Essentia for key, librosa for BPM/beats/energy.
    """
    sr = sr or 44100
    y, file_sr = librosa.load(path, sr=sr, mono=True)

    key_name, scale_name = _key_essentia(path)
    bpm = _bpm_librosa(y, sr)
    beats = _beats_librosa(y, sr)
    energy = _energy_librosa(y, sr)
    duration_sec = float(len(y) / sr)

    return SongAnalysis(
        bpm=bpm,
        key=key_name,
        key_scale=scale_name,
        beats=beats,
        energy=energy,
        duration_sec=duration_sec,
        path=path,
    )
