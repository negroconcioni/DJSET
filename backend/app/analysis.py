"""Musical analysis: BPM, key (chroma_cqt + chroma_stft), beats, energy. Camelot Wheel for LLM."""
from pathlib import Path
from typing import Optional

import librosa
import numpy as np

from .models import SongAnalysis

# Notas cromáticas (12 bins)
_NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Krumhansl-Schmuckler key profiles (major, minor)
_KEY_PROFILE_MAJOR = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88], dtype=np.float32
)
_KEY_PROFILE_MINOR = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17], dtype=np.float32
)

# Camelot Wheel: A = major, B = minor. 1A=C, 2A=G, 3A=D, ... 1B=Am, 2B=Em, ...
# Circle of fifths order: C G D A E B F# Db Ab Eb Bb F -> 1A..12A
_CAMELOT_MAJOR = [1, 8, 3, 10, 5, 12, 7, 2, 9, 4, 11, 6]   # C C# D D# E F F# G G# A A# B
_CAMELOT_MINOR = [11, 5, 8, 7, 2, 10, 4, 9, 6, 1, 12, 3]   # Am Bm C#m D#m Em F#m G#m Dm Gm Cm Fm Bbm


def _key_from_chroma(chroma_avg: np.ndarray) -> tuple[str, str, float]:
    """Key from averaged chroma using Krumhansl-Schmuckler. Returns (note_name, scale, confidence 0-1)."""
    if chroma_avg.size != 12:
        return "C", "major", 0.5
    chroma_avg = chroma_avg.astype(np.float32)
    best_corr = -np.inf
    best_key = 0
    best_scale = "major"
    for shift in range(12):
        rotated = np.roll(chroma_avg, -shift)
        corr_maj = np.corrcoef(rotated, _KEY_PROFILE_MAJOR)[0, 1]
        corr_min = np.corrcoef(rotated, _KEY_PROFILE_MINOR)[0, 1]
        if not np.isfinite(corr_maj):
            corr_maj = 0
        if not np.isfinite(corr_min):
            corr_min = 0
        if corr_maj > best_corr:
            best_corr = corr_maj
            best_key = shift
            best_scale = "major"
        if corr_min > best_corr:
            best_corr = corr_min
            best_key = shift
            best_scale = "minor"
    # Normalize correlation to 0-1 (typical range ~0.3–0.9)
    confidence = float(np.clip((best_corr + 0.2) / 1.1, 0.0, 1.0))
    return _NOTES[best_key], best_scale, confidence


def detect_key(y: np.ndarray, sr: int) -> tuple[str, str, str, float]:
    """
    Detect tonalidad con Librosa: chroma_cqt (principal) + chroma_stft; Krumhansl-Schmuckler → Camelot.
    Returns (key_name, scale, camelot, key_confidence 0-1).
    """
    try:
        # Chroma CQT: mejor para tonalidad (espectro logarítmico)
        chroma_cqt = librosa.feature.chroma_cqt(
            y=y, sr=sr, hop_length=2048, bins_per_octave=36
        )
        mean_cqt = np.mean(chroma_cqt, axis=1)
        if mean_cqt.size != 12:
            return "C", "major", "1A", 0.5
        # Chroma STFT: complementario para transitorios
        chroma_stft = librosa.feature.chroma_stft(y=y, sr=sr, hop_length=2048)
        mean_stft = np.mean(chroma_stft, axis=1)
        if mean_stft.size != 12:
            key_name, scale, conf = _key_from_chroma(mean_cqt)
            camelot = key_to_camelot(key_name, scale)
            return key_name, scale, camelot, conf
        # Combinar: CQT más fiable para key
        combined = 0.6 * mean_cqt + 0.4 * mean_stft
        key_name, scale, conf = _key_from_chroma(combined)
        camelot = key_to_camelot(key_name, scale)
        return key_name, scale, camelot, conf
    except Exception:
        return "C", "major", "1A", 0.5


def key_to_camelot(key_name: str, scale: str) -> str:
    """Mapea (nota, escala) a código Camelot Wheel (ej: 8A, 1B)."""
    key_name = (key_name or "C").strip()
    scale = (scale or "major").lower()
    try:
        idx = _NOTES.index(key_name)
    except ValueError:
        return "1A"
    if scale == "minor":
        num = _CAMELOT_MINOR[idx]
        return f"{num}B"
    num = _CAMELOT_MAJOR[idx]
    return f"{num}A"


def key_readable(key_name: str, scale: str) -> str:
    """Formato legible: 'C Major', 'A Minor'."""
    scale_cap = (scale or "major").capitalize()
    return f"{key_name or 'C'} {scale_cap}"


def harmonic_distance_camelot(camelot_a: str, camelot_b: str) -> int:
    """
    Distancia armónica en la rueda Camelot (0 = mismo tono, 1 = vecino, 2+ = lejano).
    Mismo número + misma letra = 0; mismo número + distinta letra (relativo) = 0;
    número adyacente (±1 en la rueda) = 1; resto = min(|n1-n2|, 12-|n1-n2|).
    """
    if not camelot_a or not camelot_b:
        return 6
    camelot_a = camelot_a.strip().upper()
    camelot_b = camelot_b.strip().upper()
    try:
        num_a = int(camelot_a[:-1])
        letter_a = camelot_a[-1]
        num_b = int(camelot_b[:-1])
        letter_b = camelot_b[-1]
    except (ValueError, IndexError):
        return 6
    if num_a == num_b and letter_a == letter_b:
        return 0
    if num_a == num_b and letter_a != letter_b:
        return 0  # relativo mayor/menor
    dist = abs(num_a - num_b)
    dist = min(dist, 12 - dist)
    return dist


def _key_librosa_fallback(y: np.ndarray, sr: int) -> tuple[str, str, float]:
    """Fallback: estimar key con chroma STFT cuando detect_key falla. Returns (key_name, scale, confidence)."""
    try:
        chroma = librosa.feature.chroma_stft(y=y, sr=sr, hop_length=2048)
        mean_chroma = np.mean(chroma, axis=1)
        if mean_chroma.size == 12:
            k, s, c = _key_from_chroma(mean_chroma.astype(np.float32))
            return k, s, c
    except Exception:
        pass
    return "C", "major", 0.5


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


BEATS_PER_BAR = 4
BARS_PER_PHRASE = 32


def _phrase_starts_and_outro(bpm: float, duration_sec: float) -> tuple[list[float], float]:
    """
    Phrasing mastery: inicios de frase cada 32 compases y estimación de inicio del outro.
    El punto de mezcla debe alinearse con inicio de frase en B y outro/frase en A.
    """
    if bpm <= 0 or duration_sec <= 0:
        return [0.0], max(0.0, duration_sec - 60.0)
    bar_duration_sec = (BEATS_PER_BAR * 60.0) / bpm
    phrase_duration_sec = BARS_PER_PHRASE * bar_duration_sec
    phrase_starts: list[float] = []
    t = 0.0
    while t < duration_sec:
        phrase_starts.append(round(t, 2))
        t += phrase_duration_sec
    if not phrase_starts:
        phrase_starts = [0.0]
    # Outro: últimas 2 frases o último 25% del track (zona de transición/outro)
    outro_start = duration_sec - min(2 * phrase_duration_sec, duration_sec * 0.25)
    outro_start = max(0.0, round(outro_start, 2))
    return phrase_starts, outro_start


def analyze_song(path: Path, sr: Optional[int] = None) -> SongAnalysis:
    """
    Analyze one audio file: BPM, key (chroma_cqt + chroma_stft), Camelot, beats, energy.
    """
    sr = sr or 44100
    y, _ = librosa.load(path, sr=sr, mono=True)

    try:
        key_name, scale_name, key_camelot, key_confidence = detect_key(y, sr)
    except Exception:
        key_name, scale_name, key_conf = _key_librosa_fallback(y, sr)
        key_camelot = key_to_camelot(key_name, scale_name)
        key_confidence = key_conf

    bpm = _bpm_librosa(y, sr)
    beats = _beats_librosa(y, sr)
    energy = _energy_librosa(y, sr)
    duration_sec = float(len(y) / sr)
    phrase_starts_sec, outro_start_sec = _phrase_starts_and_outro(bpm, duration_sec)

    return SongAnalysis(
        bpm=bpm,
        key=key_name,
        key_scale=scale_name,
        key_camelot=key_camelot,
        key_confidence=key_confidence,
        beats=beats,
        energy=energy,
        duration_sec=duration_sec,
        phrase_starts_sec=phrase_starts_sec,
        outro_start_sec=outro_start_sec,
        path=path,
    )
