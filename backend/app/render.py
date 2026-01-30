"""Offline audio render: time-stretch, pitch-shift, crossfade. Uses Rubber Band + FFmpeg."""
import subprocess
from pathlib import Path
from typing import Optional

from .models import MixStrategy, SongAnalysis


def _run(cmd: list[str], cwd: Optional[Path] = None) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def _rubberband(
    input_path: Path,
    output_path: Path,
    stretch_ratio: float,
    pitch_semitones: float,
) -> None:
    """Run Rubber Band: time stretch and pitch shift."""
    if abs(stretch_ratio - 1.0) < 1e-6 and abs(pitch_semitones) < 1e-6:
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

    _rubberband(
        path_a,
        a_proc,
        strategy.song_a_stretch_ratio,
        strategy.song_a_pitch_semitones,
    )
    _rubberband(
        path_b,
        b_proc,
        strategy.song_b_stretch_ratio,
        strategy.song_b_pitch_semitones,
    )

    dur_a = _duration(a_proc)
    dur_b = _duration(b_proc)

    transition_start = min(strategy.song_a_transition_start_sec, dur_a - 1.0)
    crossfade = min(strategy.crossfade_sec, dur_a - transition_start, 20.0)
    crossfade = max(1.0, crossfade)

    # 👉 CLAVE: NO concatenamos audio "mid" como archivo separado
    # usamos filter_complex con acrossfade + atrim

    _run([
        "ffmpeg", "-y",
        "-i", str(a_proc),
        "-i", str(b_proc),
        "-filter_complex",
        (
            f"[0:a]atrim=0:{transition_start},asetpts=PTS-STARTPTS[a0];"
            f"[0:a]atrim={transition_start}:{transition_start + crossfade},asetpts=PTS-STARTPTS[a1];"
            f"[1:a]atrim=0:{crossfade},asetpts=PTS-STARTPTS[b0];"
            f"[1:a]atrim={crossfade},asetpts=PTS-STARTPTS[b1];"
            f"[a1][b0]acrossfade=d={crossfade}:c1=tri:c2=tri[x];"
            f"[a0][x][b1]concat=n=3:v=0:a=1[out]"
        ),
        "-map", "[out]",
        "-acodec", "pcm_s16le",
        str(output_path),
    ])

    # Limpieza
    for p in (a_proc, b_proc):
        try:
            p.unlink()
        except OSError:
            pass

    return output_path
