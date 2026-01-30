"""FastAPI app: upload and generate mix endpoints."""
import uuid
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel

from .analysis import analyze_song
from .config import settings
from .decision import get_mix_strategy
from .models import SongAnalysis
from .render import render_mix


class GenerateBody(BaseModel):
    """Optional body for POST /generate: DJ style prompt."""

    dj_style_prompt: Optional[str] = None

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

# In-memory store for MVP: session_id -> (path_a, path_b)
# In production use Redis or DB
_sessions: dict[str, tuple[Path, Path]] = {}


def _ensure_dirs() -> None:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.output_dir.mkdir(parents=True, exist_ok=True)


def _save_upload(upload: UploadFile, session_id: str, label: str) -> Path:
    _ensure_dirs()
    ext = Path(upload.filename or "audio").suffix or ".wav"
    if ext.lower() not in (".wav", ".mp3", ".flac", ".ogg", ".m4a"):
        ext = ".wav"
    path = settings.upload_dir / f"{session_id}_{label}{ext}"
    content = upload.file.read()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(400, f"File too large (max {settings.max_upload_mb} MB)")
    path.write_bytes(content)
    return path


@app.post("/session")
def create_session() -> dict:
    """Create a session; use returned session_id for uploads and generate."""
    session_id = str(uuid.uuid4())
    _sessions[session_id] = (None, None)
    return {"session_id": session_id}


@app.post("/upload/{session_id}/a")
async def upload_song_a(session_id: str, file: UploadFile = File(...)) -> dict:
    """Upload song A (outgoing)."""
    if session_id not in _sessions:
        raise HTTPException(404, "Session not found")
    path = _save_upload(file, session_id, "a")
    _sessions[session_id] = (path, _sessions[session_id][1])
    return {"session_id": session_id, "file": "a", "path": str(path)}


@app.post("/upload/{session_id}/b")
async def upload_song_b(session_id: str, file: UploadFile = File(...)) -> dict:
    """Upload song B (incoming)."""
    if session_id not in _sessions:
        raise HTTPException(404, "Session not found")
    path = _save_upload(file, session_id, "b")
    _sessions[session_id] = (_sessions[session_id][0], path)
    return {"session_id": session_id, "file": "b", "path": str(path)}


@app.post("/generate/{session_id}")
async def generate_mix(
    session_id: str,
    body: Optional[GenerateBody] = Body(default=None),
) -> dict:
    """
    Analyze both songs, get DJ strategy (LLM or heuristics), render mix offline, return download info.
    Optional body: { "dj_style_prompt": "You are a DJ playing a warm-up set at sunset." }
    """
    if session_id not in _sessions:
        raise HTTPException(404, "Session not found")
    path_a, path_b = _sessions[session_id]
    if path_a is None or path_b is None:
        raise HTTPException(400, "Upload both song A and song B first")

    _ensure_dirs()
    out_path = settings.output_dir / f"{session_id}_mix.wav"
    dj_style_prompt = body.dj_style_prompt if body and body.dj_style_prompt else None

    try:
        analysis_a = analyze_song(path_a, settings.default_sr)
        analysis_b = analyze_song(path_b, settings.default_sr)
    except Exception as e:
        raise HTTPException(422, f"Analysis failed: {e}") from e

    try:
        strategy = get_mix_strategy(analysis_a, analysis_b, dj_style_prompt=dj_style_prompt)
    except Exception as e:
        raise HTTPException(502, f"Mix decision failed: {e}") from e

    try:
        render_mix(
            path_a,
            path_b,
            analysis_a,
            analysis_b,
            strategy,
            out_path,
            work_dir=settings.output_dir,
        )
    except Exception as e:
        raise HTTPException(500, f"Render failed: {e}") from e

    return {
        "session_id": session_id,
        "download_url": f"/download/{session_id}",
        "analysis_a": analysis_a.model_dump(mode="json", exclude={"path"}),
        "analysis_b": analysis_b.model_dump(mode="json", exclude={"path"}),
        "strategy": strategy.model_dump(mode="json"),
    }


@app.get("/download/{session_id}")
def download_mix(session_id: str) -> FileResponse:
    """Download the mixed WAV file for the session."""
    path = settings.output_dir / f"{session_id}_mix.wav"
    if not path.exists():
        raise HTTPException(404, "Mix not ready. Call POST /generate/{session_id} first.")
    return FileResponse(path, filename="automix_mix.wav", media_type="audio/wav")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# Frontend: static files and index
_frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
if _frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_frontend_dir)), name="static")

    @app.get("/")
    def index():
        return FileResponse(_frontend_dir / "index.html")
