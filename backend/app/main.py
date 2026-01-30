"""FastAPI app: 100% stateless — session temp dirs, Redis TTL 1h, stream+delete on download."""
import asyncio
import json
import shutil
import threading
import uuid
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Literal, Optional

from fastapi import BackgroundTasks, Body, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .admin_config import get_admin_config, set_admin_config
from .analysis import analyze_song
from .audio.analyzer import get_audio_metadata
from .audio_analyzer import analyze_track_structure
from .config import settings
from .decision import get_mix_strategy
from .models import MixStrategy, SongAnalysis
from .render import render_mix
from .sequencer import analyze_tracks, build_roadmap, sort_playlist
from .redis_store import get_job as redis_get_job, set_job as redis_set_job

JobStatus = Literal["processing", "ready", "failed"]


class GenerateBody(BaseModel):
    """Body for POST /generate: user instruction passed directly to DJ Brain."""

    user_prompt: Optional[str] = None
    dj_style_prompt: Optional[str] = None  # backward compat; ignored if user_prompt is set


class GenerateStatusResponse(BaseModel):
    """Response for GET /generate/{session_id}/status."""

    session_id: str
    status: JobStatus
    download_url: Optional[str] = None
    error: Optional[str] = None
    analysis_a: Optional[dict[str, Any]] = None
    analysis_b: Optional[dict[str, Any]] = None
    strategy: Optional[dict[str, Any]] = None


class AdminConfigBody(BaseModel):
    """Body for POST /admin/config: apply admin settings in real time."""

    system_prompt: Optional[str] = None
    mix_sensitivity: Optional[float] = None
    default_bars: Optional[int] = None
    bass_swap_intensity: Optional[float] = None
    presets: Optional[list[dict[str, Any]]] = None
    allow_instruments_ai: Optional[bool] = None
    allow_vocals_ai: Optional[bool] = None


app = FastAPI(
    title="AutoMix AI",
    description="MVP: upload two songs, get one mixed file (offline).",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Stateless: solo memoria volátil cuando no hay Redis (two-track)
_sessions: dict[str, Path] = {}  # session_id -> session_dir
_job_status: dict[str, JobStatus] = {}
_job_result: dict[str, dict[str, Any]] = {}
_job_error: dict[str, str] = {}
_folder_jobs: dict[str, dict[str, Any]] = {}  # sync process-folder (sin Celery)


def _session_dir(session_id: str) -> Path:
    """Directorio temporal por sesión: session_root / session_id. Se borra tras descarga o TTL."""
    return settings.session_root / session_id


def _get_or_create_session_dir(session_id: str) -> Path:
    """Crea session_root y session_dir si no existen. Devuelve Path del directorio de sesión."""
    settings.session_root.mkdir(parents=True, exist_ok=True)
    d = _session_dir(session_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _delete_session_dir(session_id: str) -> None:
    """Borra el directorio de sesión (uploads + output). Garantía de borrado."""
    d = _session_dir(session_id)
    if d.exists():
        try:
            shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def _cleanup_abandoned_sessions() -> int:
    """Borra session_dirs cuyo job ya no está en Redis (TTL expirado). Devuelve cantidad eliminada."""
    if not settings.session_root.exists():
        return 0
    removed = 0
    for child in list(settings.session_root.iterdir()):
        if not child.is_dir():
            continue
        session_id = child.name
        if settings.use_celery:
            if redis_get_job(session_id) is None:
                try:
                    shutil.rmtree(child, ignore_errors=True)
                    removed += 1
                except OSError:
                    pass
        else:
            if session_id not in _sessions and session_id not in _job_status and session_id not in _folder_jobs:
                try:
                    shutil.rmtree(child, ignore_errors=True)
                    removed += 1
                except OSError:
                    pass
    return removed


def _save_upload_to_session(upload: UploadFile, session_id: str, label: str) -> Path:
    """Guarda un upload en el directorio de sesión (song_a / song_b)."""
    session_dir = _get_or_create_session_dir(session_id)
    ext = Path(upload.filename or "audio").suffix or ".wav"
    if ext.lower() not in (".wav", ".mp3", ".flac", ".ogg", ".m4a"):
        ext = ".wav"
    path = session_dir / f"song_{label}{ext}"
    content = upload.file.read()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(400, f"File too large (max {settings.max_upload_mb} MB)")
    path.write_bytes(content)
    return path


def _run_render_background(
    session_id: str,
    path_a: Path,
    path_b: Path,
    analysis_a: SongAnalysis,
    analysis_b: SongAnalysis,
    strategy: MixStrategy,
    session_dir: Path,
) -> None:
    """Background: render a session_dir/mix.wav. Try/finally: si falla, borra session_dir."""
    out_path = session_dir / "mix.wav"
    succeeded = False
    try:
        render_mix(
            path_a,
            path_b,
            analysis_a,
            analysis_b,
            strategy,
            out_path,
            work_dir=session_dir,
        )
        payload = {
            "status": "ready",
            "set_path": str(out_path),
            "session_dir": str(session_dir),
            "analysis_a": analysis_a.model_dump(mode="json", exclude={"path"}),
            "analysis_b": analysis_b.model_dump(mode="json", exclude={"path"}),
            "strategy": strategy.model_dump(mode="json"),
        }
        if settings.use_celery:
            redis_set_job(session_id, payload)
        else:
            _job_status[session_id] = "ready"
            _job_result[session_id] = {
                "analysis_a": payload["analysis_a"],
                "analysis_b": payload["analysis_b"],
                "strategy": payload["strategy"],
                "set_path": str(out_path),
                "session_dir": str(session_dir),
            }
            _job_error.pop(session_id, None)
        succeeded = True
    except Exception as e:
        if settings.use_celery:
            redis_set_job(session_id, {"status": "failed", "error": str(e)})
        else:
            _job_status[session_id] = "failed"
            _job_error[session_id] = str(e)
            _job_result.pop(session_id, None)
    finally:
        if not succeeded:
            _delete_session_dir(session_id)


def _run_folder_pipeline(session_id: str, session_dir: Path) -> None:
    """Background: Sequencer Agent en session_dir. Try/finally: si falla, borra session_dir."""
    import subprocess

    def set_phase(phase: str, current: Optional[int] = None, total: Optional[int] = None) -> None:
        job = _folder_jobs.get(session_id)
        if job and job.get("status") == "processing":
            job["phase"] = phase
            if current is not None:
                job["current_segment"] = current
            if total is not None:
                job["total_segments"] = total

    work_dir = session_dir
    exts = (".wav", ".mp3", ".flac", ".ogg", ".m4a")
    paths = sorted(p for p in work_dir.iterdir() if p.is_file() and p.suffix.lower() in exts)
    if len(paths) < 2:
        _folder_jobs[session_id] = {"status": "failed", "error": "Need at least 2 tracks"}
        _delete_session_dir(session_id)
        return
    set_path = work_dir / "set_final.wav"
    tracklist_path = work_dir / "tracklist.txt"
    succeeded = False
    try:
        set_phase("analyzing")
        analyzed = analyze_tracks(paths, sr=settings.default_sr)
        if len(analyzed) < 2:
            _folder_jobs[session_id] = {"status": "failed", "error": "Could not analyze at least 2 tracks"}
            return
        set_phase("sequencing")
        ordered = sort_playlist(analyzed, energy_curve_ascending=True)
        roadmap = build_roadmap(ordered)
        total_segments = len(roadmap)
        _folder_jobs[session_id]["total_segments"] = total_segments
        segment_paths: list[Path] = []
        tracklist_lines: list[str] = ["OPUS AI — Tracklist (Set completo)", "=" * 60]
        for idx, (path_a, path_b, analysis_a, analysis_b) in enumerate(roadmap):
            set_phase("rendering", current=idx + 1, total=total_segments)
            metadata_a = get_audio_metadata(path_a) if path_a.exists() else {}
            metadata_b = get_audio_metadata(path_b) if path_b.exists() else {}
            try:
                track_structure_a = analyze_track_structure(path_a, sr=settings.default_sr)
                track_structure_b = analyze_track_structure(path_b, sr=settings.default_sr)
            except Exception:
                track_structure_a = track_structure_b = None
            strategy = get_mix_strategy(
                analysis_a,
                analysis_b,
                dj_style_prompt=None,
                audio_metadata_a=metadata_a,
                audio_metadata_b=metadata_b,
                track_structure_a=track_structure_a,
                track_structure_b=track_structure_b,
            )
            seg_path = work_dir / f"seg_{idx}.wav"
            render_mix(
                path_a,
                path_b,
                analysis_a,
                analysis_b,
                strategy,
                seg_path,
                work_dir=work_dir,
            )
            segment_paths.append(seg_path)
            tracklist_lines.append("")
            tracklist_lines.append(f"#{idx + 1}  A: {path_a.name}  →  B: {path_b.name}")
            tracklist_lines.append(f"  BPM A={analysis_a.bpm:.1f}  B={analysis_b.bpm:.1f}  |  Key A={analysis_a.key} {analysis_a.key_scale}  B={analysis_b.key} {analysis_b.key_scale}")
            tracklist_lines.append(f"  Razón: {strategy.reasoning or '—'}")
            if strategy.dj_comment:
                tracklist_lines.append(f"  DJ: {strategy.dj_comment}")
        if not segment_paths:
            _folder_jobs[session_id] = {"status": "failed", "error": "No segments rendered"}
            return
        set_phase("finalizing")
        concat_list = work_dir / "concat.txt"
        with open(concat_list, "w") as f:
            for p in segment_paths:
                path_str = str(p.resolve()).replace("\\", "/")
                f.write(f"file '{path_str}'\n")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(set_path)],
            check=True,
            capture_output=True,
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
        with open(tracklist_path, "w", encoding="utf-8") as f:
            f.write("\n".join(tracklist_lines))
        _folder_jobs[session_id] = {"status": "ready", "set_path": set_path, "tracklist_path": tracklist_path, "session_dir": str(session_dir)}
        succeeded = True
    except Exception as e:
        _folder_jobs[session_id] = {"status": "failed", "error": str(e)}
    finally:
        if not succeeded:
            _delete_session_dir(session_id)


@app.post("/session")
def create_session() -> dict:
    """Crea una sesión; el directorio temporal se crea en el primer upload."""
    session_id = str(uuid.uuid4())
    if settings.use_celery:
        redis_set_job(session_id, {"status": "new"})  # placeholder TTL 1h
    else:
        _sessions[session_id] = None  # se reemplaza por session_dir en el primer upload
    return {"session_id": session_id}


@app.post("/upload/{session_id}/a")
async def upload_song_a(session_id: str, file: UploadFile = File(...)) -> dict:
    """Upload song A (outgoing). Se guarda en el directorio temporal de la sesión."""
    if not settings.use_celery and session_id not in _sessions:
        raise HTTPException(404, "Session not found")
    if settings.use_celery and redis_get_job(session_id) is None:
        raise HTTPException(404, "Session not found")
    path = _save_upload_to_session(file, session_id, "a")
    if not settings.use_celery:
        _sessions[session_id] = path.parent
    else:
        job = redis_get_job(session_id) or {}
        job["session_dir"] = str(path.parent)
        job["status"] = "uploading"
        redis_set_job(session_id, job)
    return {"session_id": session_id, "file": "a", "path": str(path)}


@app.post("/upload/{session_id}/b")
async def upload_song_b(session_id: str, file: UploadFile = File(...)) -> dict:
    """Upload song B (incoming). Se guarda en el directorio temporal de la sesión."""
    if not settings.use_celery and session_id not in _sessions:
        raise HTTPException(404, "Session not found")
    if settings.use_celery and redis_get_job(session_id) is None:
        raise HTTPException(404, "Session not found")
    path = _save_upload_to_session(file, session_id, "b")
    if not settings.use_celery:
        _sessions[session_id] = path.parent
    else:
        job = redis_get_job(session_id) or {}
        job["session_dir"] = str(path.parent)
        job["status"] = "uploading"
        redis_set_job(session_id, job)
    return {"session_id": session_id, "file": "b", "path": str(path)}


def _get_two_track_paths(session_id: str) -> tuple[Optional[Path], Optional[Path], Path]:
    """Devuelve (path_a, path_b, session_dir). Levanta HTTPException si no hay sesión o faltan archivos."""
    session_dir: Optional[Path] = None
    if settings.use_celery:
        job = redis_get_job(session_id)
        if job and job.get("session_dir"):
            session_dir = Path(job["session_dir"])
        else:
            session_dir = _session_dir(session_id) if _session_dir(session_id).exists() else None
    else:
        session_dir = _sessions.get(session_id) if isinstance(_sessions.get(session_id), Path) else None
    if not session_dir or not session_dir.exists():
        raise HTTPException(404, "Session not found")
    path_a = next((p for p in session_dir.iterdir() if p.is_file() and p.name.startswith("song_a")), None)
    path_b = next((p for p in session_dir.iterdir() if p.is_file() and p.name.startswith("song_b")), None)
    return path_a, path_b, session_dir


@app.post("/generate/{session_id}")
async def generate_mix(
    session_id: str,
    background_tasks: BackgroundTasks,
    body: Optional[GenerateBody] = Body(default=None),
) -> dict:
    """
    Inicia la generación de la mezcla. Devuelve de inmediato con status 'processing'.
    Poll GET /generate/{session_id}/status; luego GET /download/{session_id}. Tras descargar, el directorio de sesión se borra.
    """
    path_a, path_b, session_dir = _get_two_track_paths(session_id)
    if path_a is None or path_b is None:
        raise HTTPException(400, "Upload both song A and song B first")

    user_prompt = None
    if body:
        user_prompt = (body.user_prompt or body.dj_style_prompt or "").strip() or None

    try:
        metadata_a = get_audio_metadata(path_a)
        metadata_b = get_audio_metadata(path_b)
    except Exception as e:
        raise HTTPException(422, f"Audio metadata failed: {e}") from e

    try:
        analysis_a = analyze_song(path_a, settings.default_sr)
        analysis_b = analyze_song(path_b, settings.default_sr)
    except Exception as e:
        raise HTTPException(422, f"Analysis failed: {e}") from e

    try:
        track_structure_a = analyze_track_structure(path_a, sr=settings.default_sr)
        track_structure_b = analyze_track_structure(path_b, sr=settings.default_sr)
    except Exception:
        track_structure_a = track_structure_b = None

    try:
        strategy = get_mix_strategy(
            analysis_a,
            analysis_b,
            dj_style_prompt=user_prompt,
            audio_metadata_a=metadata_a,
            audio_metadata_b=metadata_b,
            track_structure_a=track_structure_a,
            track_structure_b=track_structure_b,
        )
    except Exception as e:
        raise HTTPException(502, f"Mix decision failed: {e}") from e

    if strategy.dj_comment:
        print(f"[DJ] {strategy.dj_comment}", flush=True)

    if settings.use_celery:
        redis_set_job(session_id, {"status": "processing", "session_dir": str(session_dir)})
    else:
        _job_status[session_id] = "processing"
        _job_result.pop(session_id, None)
        _job_error.pop(session_id, None)

    background_tasks.add_task(
        _run_render_background,
        session_id,
        path_a,
        path_b,
        analysis_a,
        analysis_b,
        strategy,
        session_dir,
    )

    return {
        "session_id": session_id,
        "status": "processing",
        "status_url": f"/generate/{session_id}/status",
        "download_url": f"/download/{session_id}",
    }


@app.get("/generate/{session_id}/status", response_model=GenerateStatusResponse)
def get_generate_status(session_id: str) -> GenerateStatusResponse:
    """Poll del estado del job. Cuando status es 'ready', usar download_url."""
    if settings.use_celery:
        job = redis_get_job(session_id)
        if job is None:
            raise HTTPException(404, "Session not found")
        status = job.get("status", "processing")
        return GenerateStatusResponse(
            session_id=session_id,
            status=status,
            download_url=f"/download/{session_id}" if status == "ready" else None,
            error=job.get("error"),
            analysis_a=job.get("analysis_a"),
            analysis_b=job.get("analysis_b"),
            strategy=job.get("strategy"),
        )
    if session_id not in _sessions and session_id not in _job_status:
        raise HTTPException(404, "Session not found")
    status = _job_status.get(session_id, "processing")
    result = _job_result.get(session_id)
    return GenerateStatusResponse(
        session_id=session_id,
        status=status,
        download_url=f"/download/{session_id}" if status == "ready" else None,
        error=_job_error.get(session_id),
        analysis_a=result.get("analysis_a") if result else None,
        analysis_b=result.get("analysis_b") if result else None,
        strategy=result.get("strategy") if result else None,
    )


def _stream_file_then_delete(path: Path, session_id: str, delete_after: bool = True):
    """Generador: lee el archivo en chunks. Si delete_after, borra el directorio de sesión solo tras stream completo."""
    chunk_size = 1024 * 1024
    completed = False
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk
        completed = True
    finally:
        if delete_after and completed:
            _delete_session_dir(session_id)


@app.get("/download/{session_id}")
def download_mix(session_id: str) -> StreamingResponse:
    """Descarga el WAV mezclado como stream. Tras la descarga exitosa se borra el directorio de sesión."""
    path: Optional[Path] = None
    if settings.use_celery:
        job = redis_get_job(session_id)
        if not job or job.get("status") != "ready":
            raise HTTPException(404, "Mix not ready. Poll GET /generate/{session_id}/status until status is 'ready'.")
        path = Path(job.get("set_path", ""))
    else:
        if _job_status.get(session_id) != "ready":
            raise HTTPException(404, "Mix not ready. Poll GET /generate/{session_id}/status until status is 'ready'.")
        result = _job_result.get(session_id)
        path = Path(result["set_path"]) if result and result.get("set_path") else None
    if not path or not path.exists():
        raise HTTPException(404, "Mix file not found.")
    return StreamingResponse(
        _stream_file_then_delete(path, session_id, delete_after=True),
        media_type="audio/wav",
        headers={"Content-Disposition": "attachment; filename=automix_mix.wav"},
    )


@app.post("/process-folder")
async def process_folder(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(..., description="Tracks para el set (mín. 2)"),
) -> dict:
    """
    Sequencer Agent: sube múltiples tracks a un directorio temporal por sesión.
    Con Redis: encola en Celery (ai_brain + audio_worker). Sin Redis: _run_folder_pipeline en background.
    Tras descargar set/tracklist se borra el directorio de sesión.
    """
    if len(files) < 2:
        raise HTTPException(400, "Enviá al menos 2 archivos de audio")
    session_id = str(uuid.uuid4())
    session_dir = _get_or_create_session_dir(session_id)
    paths: list[Path] = []
    for i, u in enumerate(files):
        if not u.filename:
            continue
        ext = Path(u.filename).suffix or ".wav"
        if ext.lower() not in (".wav", ".mp3", ".flac", ".ogg", ".m4a"):
            ext = ".wav"
        path = session_dir / f"track_{i}{ext}"
        content = await u.read()
        if len(content) > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(400, f"Archivo {u.filename} excede {settings.max_upload_mb} MB")
        path.write_bytes(content)
        paths.append(path)
    if len(paths) < 2:
        _delete_session_dir(session_id)
        raise HTTPException(400, "Se guardaron menos de 2 archivos válidos")

    if settings.use_celery:
        redis_set_job(session_id, {"status": "processing", "phase": "analyzing", "session_dir": str(session_dir)})
        from .tasks import run_folder_pipeline
        run_folder_pipeline.delay(session_id, str(session_dir))
    else:
        _folder_jobs[session_id] = {"status": "processing", "session_dir": str(session_dir)}
        background_tasks.add_task(_run_folder_pipeline, session_id, session_dir)

    return {
        "session_id": session_id,
        "status": "processing",
        "status_url": f"/process-folder/{session_id}/status",
        "set_url": f"/process-folder/{session_id}/set",
        "tracklist_url": f"/process-folder/{session_id}/tracklist",
    }


def _folder_job_for(session_id: str) -> Optional[dict]:
    """Estado del job: desde Redis si use_celery, sino en memoria."""
    if settings.use_celery:
        job = redis_get_job(session_id)
        if job is not None:
            return job
        if _session_dir(session_id).exists():
            return {"status": "processing", "phase": "analyzing"}
        return None
    return _folder_jobs.get(session_id)


@app.get("/process-folder/{session_id}/status")
def get_process_folder_status(session_id: str) -> dict:
    """Estado del job de process-folder. phase: analyzing | sequencing | rendering | finalizing."""
    job = _folder_job_for(session_id)
    if job is None:
        raise HTTPException(404, "Session not found")
    return {
        "session_id": session_id,
        "status": job.get("status", "processing"),
        "phase": job.get("phase", "analyzing"),
        "current_segment": job.get("current_segment"),
        "total_segments": job.get("total_segments"),
        "set_url": f"/process-folder/{session_id}/set" if job.get("status") == "ready" else None,
        "tracklist_url": f"/process-folder/{session_id}/tracklist" if job.get("status") == "ready" else None,
        "error": job.get("error"),
    }


@app.get("/process-folder/{session_id}/set")
def download_folder_set(session_id: str) -> StreamingResponse:
    """Descarga el WAV del set completo. Tras la descarga se borra el directorio de sesión."""
    job = _folder_job_for(session_id)
    if not job or job.get("status") != "ready":
        raise HTTPException(404, "Set not ready. Poll GET /process-folder/{session_id}/status")
    set_path = job.get("set_path")
    if not set_path or not Path(set_path).exists():
        raise HTTPException(404, "Set file not found")
    return StreamingResponse(
        _stream_file_then_delete(Path(set_path), session_id, delete_after=True),
        media_type="audio/wav",
        headers={"Content-Disposition": "attachment; filename=opus_set.wav"},
    )


@app.get("/process-folder/{session_id}/tracklist")
def download_folder_tracklist(session_id: str) -> StreamingResponse:
    """Descarga el tracklist. No borra la sesión (se borra al descargar el set o por TTL)."""
    job = _folder_job_for(session_id)
    if not job or job.get("status") != "ready":
        raise HTTPException(404, "Tracklist not ready. Poll GET /process-folder/{session_id}/status")
    tracklist_path = job.get("tracklist_path")
    if not tracklist_path or not Path(tracklist_path).exists():
        raise HTTPException(404, "Tracklist file not found")
    return StreamingResponse(
        _stream_file_then_delete(Path(tracklist_path), session_id, delete_after=False),
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=opus_set_tracklist.txt"},
    )


@app.post("/cleanup")
def cleanup_abandoned() -> dict:
    """Borra directorios de sesión cuyo job ya no está en Redis (TTL expirado). Stateless."""
    removed = _cleanup_abandoned_sessions()
    return {"removed": removed}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Admin panel: config in real time (no restart)
# ---------------------------------------------------------------------------

@app.get("/admin/config")
def admin_get_config() -> dict:
    """Return current admin config (system_prompt, sliders, presets) for the control panel."""
    return get_admin_config()


@app.post("/admin/config")
def admin_post_config(body: Optional[AdminConfigBody] = Body(default=None)) -> dict:
    """Apply admin config changes in real time. Returns updated config."""
    if not body:
        return get_admin_config()
    set_admin_config(
        system_prompt=body.system_prompt,
        mix_sensitivity=body.mix_sensitivity,
        default_bars=body.default_bars,
        bass_swap_intensity=body.bass_swap_intensity,
        presets=body.presets,
        allow_instruments_ai=body.allow_instruments_ai,
        allow_vocals_ai=body.allow_vocals_ai,
    )
    return get_admin_config()


@app.post("/admin/update-config")
def admin_update_config(body: Optional[AdminConfigBody] = Body(default=None)) -> dict:
    """Same as POST /admin/config: save configuration and apply in real time (The Lab: SAVE CONFIGURATION & TRAIN)."""
    return admin_post_config(body)


# ---------------------------------------------------------------------------
# Socket.IO: real-time progress (workers publish to Redis, API forwards to client)
# ---------------------------------------------------------------------------
_progress_queue: Optional[Queue] = None
_sio = None

if settings.use_celery:
    try:
        import socketio
        _sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
        _progress_queue = Queue()

        @_sio.event
        async def connect(sid, environ):
            pass

        @_sio.event
        async def join_session(sid, data):
            if data and isinstance(data, dict) and data.get("session_id"):
                await _sio.enter_room(sid, str(data["session_id"]))

        def _redis_progress_listener():
            try:
                import redis
                r = redis.from_url(settings.redis_url, decode_responses=True)
                pub = r.pubsub()
                pub.psubscribe("opus:progress:*")
                for message in pub.listen():
                    if message.get("type") == "pmessage":
                        channel = message.get("channel", "")
                        session_id = channel.replace("opus:progress:", "") if channel else ""
                        try:
                            payload = json.loads(message.get("data") or "{}")
                            if session_id and _progress_queue is not None:
                                _progress_queue.put((session_id, payload))
                        except Exception:
                            pass
            except Exception:
                pass

        @app.on_event("startup")
        async def _start_socketio_forwarder():
            if _sio is None or _progress_queue is None:
                return
            t = threading.Thread(target=_redis_progress_listener, daemon=True)
            t.start()

            async def forwarder():
                while True:
                    try:
                        session_id, data = await asyncio.get_event_loop().run_in_executor(
                            None, lambda: _progress_queue.get(timeout=0.5)
                        )
                        await _sio.emit("progress", data, room=session_id)
                    except Empty:
                        await asyncio.sleep(0.05)
                    except Exception:
                        await asyncio.sleep(0.2)

            asyncio.create_task(forwarder())
    except Exception:
        _sio = None
        _progress_queue = None

asgi_app = app
if _sio is not None:
    try:
        import socketio
        asgi_app = socketio.ASGIApp(_sio, app)
    except Exception:
        pass


# Frontend: static files and index
_frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
if _frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_frontend_dir)), name="static")

    @app.get("/")
    def index():
        return FileResponse(_frontend_dir / "index.html")

    @app.get("/admin")
    def admin():
        return FileResponse(_frontend_dir / "admin.html")
