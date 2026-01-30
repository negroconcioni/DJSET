"""Celery tasks: ai_brain (sequencer + strategy), audio_worker (render segment). Stateless: session_dir, try/finally."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import List

from celery import chord, group
from .celery_app import app
from .config import settings
from .redis_store import get_job, publish_progress, set_job
from .render import render_mix
from .models import MixStrategy, SongAnalysis
from .sequencer import analyze_tracks, build_roadmap, sort_playlist
from .admin_config import get_allow_instruments_ai, get_allow_vocals_ai
from .decision import get_mix_strategy
from .sample_library import get_compatible_samples
from .audio.analyzer import get_audio_metadata
from .audio_analyzer import analyze_track_structure


def _delete_session_dir(session_dir: Path) -> None:
    """Garantía de borrado: borra el directorio de sesión."""
    if session_dir.exists():
        try:
            shutil.rmtree(session_dir, ignore_errors=True)
        except OSError:
            pass


@app.task(bind=True, name="app.tasks.run_folder_pipeline", queue="ai_brain")
def run_folder_pipeline(self, session_id: str, session_dir_str: str) -> None:
    """
    AI-brain / Sequencer: trabaja en session_dir (temp). Try/finally: si falla, borra session_dir.
    Encola render_segment en audio_worker y finalize_set al terminar.
    """
    work_dir = Path(session_dir_str)
    if not work_dir.exists():
        set_job(session_id, {"status": "failed", "error": "Session directory not found"})
        return

    exts = (".wav", ".mp3", ".flac", ".ogg", ".m4a")
    paths = sorted(p for p in work_dir.iterdir() if p.is_file() and p.suffix.lower() in exts)
    set_job(session_id, {"status": "processing", "phase": "analyzing", "session_dir": session_dir_str})
    publish_progress(session_id, {"phase": "analyzing", "message": "Analizando armonía y BPM de los tracks..."})

    succeeded = False
    try:
        if len(paths) < 2:
            set_job(session_id, {"status": "failed", "error": "Need at least 2 tracks"})
            return

        analyzed = analyze_tracks(paths, sr=settings.default_sr)
        if len(analyzed) < 2:
            set_job(session_id, {"status": "failed", "error": "Could not analyze at least 2 tracks"})
            return

        publish_progress(session_id, {"phase": "sequencing", "message": "Calculando secuencia óptima (Opus Engine)..."})
        set_job(session_id, {"status": "processing", "phase": "sequencing", "session_dir": session_dir_str})
        ordered = sort_playlist(analyzed, energy_curve_ascending=True)
        roadmap = build_roadmap(ordered)
        total_segments = len(roadmap)
        set_job(session_id, {"status": "processing", "phase": "rendering", "total_segments": total_segments, "session_dir": session_dir_str})

        tracklist_lines: List[str] = ["OPUS AI — Tracklist (Set completo)", "=" * 60]
        segment_tasks = []
        for idx, (path_a, path_b, analysis_a, analysis_b) in enumerate(roadmap):
            metadata_a = get_audio_metadata(path_a) if path_a.exists() else {}
            metadata_b = get_audio_metadata(path_b) if path_b.exists() else {}
            try:
                track_structure_a = analyze_track_structure(path_a, sr=settings.default_sr)
                track_structure_b = analyze_track_structure(path_b, sr=settings.default_sr)
            except Exception:
                track_structure_a = track_structure_b = None
            # Sampler Manager: antes de la IA, obtener samples compatibles con BPM/Key del segmento
            compatible_overlays = None
            if get_allow_instruments_ai() or get_allow_vocals_ai():
                avg_bpm = (analysis_a.bpm + analysis_b.bpm) / 2.0
                camelot_mix = (getattr(analysis_a, "key_camelot", None) or getattr(analysis_b, "key_camelot", None) or "").strip() or "8A"
                categories = []
                if get_allow_instruments_ai():
                    categories.append("instruments")
                if get_allow_vocals_ai():
                    categories.append("vocals")
                if categories:
                    compatible_overlays = get_compatible_samples(
                        avg_bpm, camelot_mix, categories, bpm_tolerance=5.0, max_camelot_distance=1
                    )
            strategy = get_mix_strategy(
                analysis_a, analysis_b,
                dj_style_prompt=None,
                audio_metadata_a=metadata_a, audio_metadata_b=metadata_b,
                track_structure_a=track_structure_a, track_structure_b=track_structure_b,
                compatible_overlays=compatible_overlays,
            )
            seg_path = work_dir / f"seg_{idx}.wav"
            tracklist_lines.append("")
            tracklist_lines.append(f"#{idx + 1}  A: {path_a.name}  →  B: {path_b.name}")
            tracklist_lines.append(f"  BPM A={analysis_a.bpm:.1f}  B={analysis_b.bpm:.1f}  |  Key A={analysis_a.key} {analysis_a.key_scale}  B={analysis_b.key} {analysis_b.key_scale}")
            tracklist_lines.append(f"  Razón: {strategy.reasoning or '—'}")
            if strategy.dj_comment:
                tracklist_lines.append(f"  DJ: {strategy.dj_comment}")

            strategy_dict = strategy.model_dump(mode="json")
            if getattr(strategy, "overlay_paths", None):
                strategy_dict["overlay_paths"] = [str(p) for p in strategy.overlay_paths]
        segment_tasks.append(
            render_segment.s(
                session_id,
                idx,
                total_segments,
                str(path_a),
                str(path_b),
                analysis_a.model_dump(mode="json"),
                analysis_b.model_dump(mode="json"),
                strategy_dict,
                str(seg_path),
                str(work_dir),
            )
        )

        job_state = get_job(session_id) or {}
        job_state["tracklist_lines"] = tracklist_lines
        job_state["total_segments"] = total_segments
        job_state["session_dir"] = session_dir_str
        set_job(session_id, job_state)

        chord(group(*segment_tasks))(finalize_set.s(session_id))
        succeeded = True  # chord encolado; finalize_set borra session_dir si falla
    finally:
        if not succeeded:
            _delete_session_dir(work_dir)


@app.task(bind=True, name="app.tasks.render_segment", queue="audio_worker")
def render_segment(
    self,
    session_id: str,
    idx: int,
    total_segments: int,
    path_a_str: str,
    path_b_str: str,
    analysis_a_dict: dict,
    analysis_b_dict: dict,
    strategy_dict: dict,
    seg_path_str: str,
    work_dir_str: str,
) -> str:
    """
    Audio worker: mezcla un segmento (Rubber Band + processor hsin/loudnorm/amix).
    Devuelve seg_path para que finalize_set concatene.
    """
    path_a = Path(path_a_str)
    path_b = Path(path_b_str)
    seg_path = Path(seg_path_str)
    work_dir = Path(work_dir_str)
    analysis_a = SongAnalysis.model_validate(analysis_a_dict)
    analysis_b = SongAnalysis.model_validate(analysis_b_dict)
    # overlay_paths: list of str -> Path
    if "overlay_paths" in strategy_dict and strategy_dict["overlay_paths"]:
        strategy_dict["overlay_paths"] = [Path(p) for p in strategy_dict["overlay_paths"]]
    strategy = MixStrategy.model_validate(strategy_dict)

    msg = f"Mezclando Track {idx + 1} de {total_segments} (Applying Bass-Swap)..."
    publish_progress(session_id, {"phase": "rendering", "current_segment": idx + 1, "total_segments": total_segments, "message": msg})

    render_mix(path_a, path_b, analysis_a, analysis_b, strategy, seg_path, work_dir=work_dir)
    return str(seg_path)


@app.task(bind=True, name="app.tasks.finalize_set", queue="ai_brain")
def finalize_set(self, session_id: str, segment_path_results: List[str]) -> None:
    """Concatena segmentos WAV y escribe tracklist en session_dir. Try/finally: si falla, borra session_dir."""
    job = get_job(session_id) or {}
    session_dir_str = job.get("session_dir")
    if not session_dir_str:
        set_job(session_id, {"status": "failed", "error": "Session directory not found"})
        return
    work_dir = Path(session_dir_str)
    set_path = work_dir / "set_final.wav"
    tracklist_path = work_dir / "tracklist.txt"

    publish_progress(session_id, {"phase": "finalizing", "message": "Masterizando set final (Loudness Pro)..."})
    set_job(session_id, {"status": "processing", "phase": "finalizing", "session_dir": session_dir_str})

    succeeded = False
    try:
        segment_paths = [Path(p) for p in segment_path_results if p]
        if not segment_paths:
            set_job(session_id, {"status": "failed", "error": "No segments rendered"})
            return

        concat_list = work_dir / "concat.txt"
        with open(concat_list, "w") as f:
            for p in segment_paths:
                if p.exists():
                    path_str = str(p.resolve()).replace("\\", "/")
                    f.write(f"file '{path_str}'\n")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(set_path)],
            check=True, capture_output=True,
        )
        for p in segment_paths:
            try:
                p.unlink()
            except OSError:
                pass
        try:
            concat_list.unlink()
        except OSError:
            pass

        tracklist_lines = job.get("tracklist_lines") or ["OPUS AI — Tracklist", "=" * 60]
        with open(tracklist_path, "w", encoding="utf-8") as f:
            f.write("\n".join(tracklist_lines))

        set_job(session_id, {"status": "ready", "set_path": str(set_path), "tracklist_path": str(tracklist_path), "session_dir": session_dir_str})
        publish_progress(session_id, {"phase": "ready", "message": "Set listo."})
        succeeded = True
    finally:
        if not succeeded:
            _delete_session_dir(work_dir)
