"""Offline audio render: Rubber Band (stretch/pitch) + processor (acrossfade sin -t/-to/atrim)."""
import subprocess
from pathlib import Path
from typing import Optional

from .audio.processor import render_professional_mix as processor_mix
from .models import MixStrategy, SongAnalysis

# Redondeo de tiempos (evita errores de precisión)
def _t(x: float) -> float:
    return round(float(x), 3)


def _run(cmd: list[str], cwd: Optional[Path] = None) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def _rubberband(
    input_path: Path,
    output_path: Path,
    stretch_ratio: float,
    pitch_semitones: float,
    *,
    skip_stretch: bool = False,
) -> None:
    """Run Rubber Band: time stretch and pitch shift. If skip_stretch True, only copy (no processing)."""
    if skip_stretch or (abs(stretch_ratio - 1.0) < 1e-6 and abs(pitch_semitones) < 1e-6):
        _run([
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-acodec", "pcm_s16le",
            str(output_path),
        ])
        return

    _run([
        "rubberband",
        "-t", str(stretch_ratio),
        "-p", str(pitch_semitones),
        str(input_path),
        str(output_path),
    ])


def _duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def render_mix(
    path_a: Path,
    path_b: Path,
    analysis_a: SongAnalysis,
    analysis_b: SongAnalysis,
    strategy: MixStrategy,
    output_path: Path,
    work_dir: Optional[Path] = None,
) -> Path:
    """
    Offline DJ-style mix:
    - Rubber Band for stretch/pitch
    - Real overlap crossfade (A fades out, B fades in)
    """
    work_dir = work_dir or output_path.parent
    work_dir.mkdir(parents=True, exist_ok=True)

    a_proc = work_dir / "a_proc.wav"
    b_proc = work_dir / "b_proc.wav"

    # Cada pista evalúa su propio stretch/pitch; no usar bpm_diff para ambas (ignoraría ajustes de B)
    skip_a = (
        abs(strategy.song_a_stretch_ratio - 1.0) < 1e-6
        and abs(strategy.song_a_pitch_semitones) < 1e-6
    )
    skip_b = (
        abs(strategy.song_b_stretch_ratio - 1.0) < 1e-6
        and abs(strategy.song_b_pitch_semitones) < 1e-6
    )

    _rubberband(
        path_a,
        a_proc,
        strategy.song_a_stretch_ratio,
        strategy.song_a_pitch_semitones,
        skip_stretch=skip_a,
    )
    _rubberband(
        path_b,
        b_proc,
        strategy.song_b_stretch_ratio,
        strategy.song_b_pitch_semitones,
        skip_stretch=skip_b,
    )

    duration_a = _t(_duration(a_proc))
    duration_b = _t(_duration(b_proc))

    # REGLA DE ORO: cross_d = min(strategy, duration_a*0.2, duration_b*0.2). Phrasing ya en decision (32 barras).
    cross_d = _t(float(strategy.crossfade_sec))
    cross_d = _t(min(cross_d, duration_a * 0.2, duration_b * 0.2))
    cross_d = _t(max(0.5, min(cross_d, 120.0)))

    # Sound Color FX: highpass en A cuando las keys chocan (harmonic_distance > 1)
    apply_highpass_a = (
        getattr(strategy, "harmonic_distance", None) is not None
        and strategy.harmonic_distance > 1
    )
    overlay_paths = getattr(strategy, "overlay_paths", None) or []
    overlay_bpms = getattr(strategy, "overlay_bpms", None) or []
    overlay_entry_sec = getattr(strategy, "overlay_entry_sec", None)
    target_bpm = (analysis_a.bpm + analysis_b.bpm) / 2.0 if overlay_paths else None
    processor_mix(
        a_proc, b_proc, output_path, cross_d,
        apply_highpass_a=apply_highpass_a,
        overlay_paths=overlay_paths,
        overlay_bpms=overlay_bpms if len(overlay_bpms) == len(overlay_paths) else None,
        target_bpm=target_bpm if overlay_paths else None,
        overlay_entry_sec=overlay_entry_sec,
    )

    # Limpieza
    for p in (a_proc, b_proc):
        try:
            p.unlink()
        except OSError:
            pass

    return output_path
