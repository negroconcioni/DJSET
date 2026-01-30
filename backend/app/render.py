"""Offline audio render: Rubber Band (stretch/pitch) + processor (acrossfade sin -t/-to/atrim). Cloud overlays: download to temp, then cleanup."""
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

from .audio.processor import render_professional_mix as processor_mix
from .audio.cloud_downloader import download_urls_to_temp, cleanup_temp_dir
from .config import settings
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
    - overlay_instrument / overlay_vocal: nombres de archivo (local); overlay_instrument_url / overlay_vocal_url: cloud (se descargan a temp, cleanup tras FFmpeg).
    - Si work_dir es None, se usa tempfile.TemporaryDirectory; al terminar se borra (stateless).
    """
    use_temp = work_dir is None
    if use_temp:
        td = tempfile.TemporaryDirectory()
        work_dir = Path(td.name)
    else:
        td = None
        work_dir = work_dir or output_path.parent
        work_dir.mkdir(parents=True, exist_ok=True)

    try:
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

        # REGLA DE ORO: cross_d = min(strategy, duration_a*0.2, duration_b*0.2); nunca superar 20% de ningún track.
        # Mínimo 0.5 aplicado al valor de estrategia; luego cap por 20% y 120s (tracks cortos pueden quedar < 0.5s).
        cross_d = _t(max(0.5, float(strategy.crossfade_sec)))
        cross_d = _t(min(cross_d, duration_a * 0.2, duration_b * 0.2))
        cross_d = _t(min(cross_d, 120.0))

        # Sound Color FX: highpass en A cuando las keys chocan (harmonic_distance > 1)
        apply_highpass_a = (
            getattr(strategy, "harmonic_distance", None) is not None
            and strategy.harmonic_distance > 1
        )
        overlay_instrument = getattr(strategy, "overlay_instrument", None)
        overlay_vocal = getattr(strategy, "overlay_vocal", None)
        overlay_paths = getattr(strategy, "overlay_paths", None) or []
        overlay_bpms = getattr(strategy, "overlay_bpms", None) or []
        overlay_entry_sec = getattr(strategy, "overlay_entry_sec", None)
        overlay_instrument_url = getattr(strategy, "overlay_instrument_url", None)
        overlay_vocal_url = getattr(strategy, "overlay_vocal_url", None)
        overlay_instrument_bpm = getattr(strategy, "overlay_instrument_bpm", None)
        overlay_vocal_bpm = getattr(strategy, "overlay_vocal_bpm", None)

        cloud_temp_dir: Optional[Path] = None
        if overlay_instrument_url or overlay_vocal_url:
            urls: List[str] = []
            bpms_cloud: List[float] = []
            for url, bpm in [(overlay_instrument_url, overlay_instrument_bpm), (overlay_vocal_url, overlay_vocal_bpm)]:
                if url and str(url).strip().startswith("http"):
                    urls.append(str(url).strip())
                    bpms_cloud.append(float(bpm) if bpm is not None and bpm > 0 else 120.0)
            if urls:
                overlay_paths_cloud, cloud_temp_dir = download_urls_to_temp(urls)
                overlay_paths = list(overlay_paths_cloud)
                overlay_bpms = bpms_cloud

        has_overlays = bool(overlay_instrument or overlay_vocal or overlay_paths)
        target_bpm = (analysis_a.bpm + analysis_b.bpm) / 2.0 if has_overlays else None

        # Cloud: overlay_paths/overlay_bpms ya rellenados por download. Local: overlay_instrument/overlay_vocal + assets_base.
        use_cloud = bool(overlay_instrument_url or overlay_vocal_url)
        try:
            processor_mix(
                a_proc, b_proc, output_path, cross_d,
                apply_highpass_a=apply_highpass_a,
                overlay_paths=overlay_paths if (overlay_paths and use_cloud) else (None if (overlay_instrument or overlay_vocal) else overlay_paths or None),
                overlay_bpms=overlay_bpms if (overlay_paths and use_cloud) else (None if (overlay_instrument or overlay_vocal) else (overlay_bpms if overlay_paths else None)),
                overlay_instrument=None if use_cloud else overlay_instrument,
                overlay_vocal=None if use_cloud else overlay_vocal,
                assets_base=None if use_cloud else (settings.assets_samples_dir if (overlay_instrument or overlay_vocal) else None),
                target_bpm=target_bpm,
                overlay_entry_sec=overlay_entry_sec,
            )
        finally:
            if cloud_temp_dir is not None:
                cleanup_temp_dir(cloud_temp_dir)

        # Limpieza: si no usamos temp dir, borrar archivos intermedios (stateless)
        if not use_temp:
            for p in (a_proc, b_proc):
                try:
                    p.unlink()
                except OSError:
                    pass
        return output_path
    finally:
        if use_temp and td is not None:
            td.cleanup()
