"""Redis store: job state (process-folder), admin config, progress pub/sub. Used when redis_url is set."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .config import settings

REDIS_KEY_JOB = "opus:job:{}"
REDIS_KEY_ADMIN_CONFIG = "opus:admin_config"
REDIS_CHAN_PROGRESS = "opus:progress:{}"
REDIS_TTL_JOB = 3600  # 1 hora: metadatos volátiles; si no descarga, se desvanecen


def _client():
    if not settings.redis_url:
        return None
    try:
        import redis
        return redis.from_url(settings.redis_url, decode_responses=True)
    except Exception:
        return None


def get_job(session_id: str) -> Optional[dict[str, Any]]:
    """Job state for process-folder (status, phase, current_segment, total_segments, set_path, tracklist_path, error)."""
    c = _client()
    if not c:
        return None
    try:
        raw = c.get(REDIS_KEY_JOB.format(session_id))
        if not raw:
            return None
        return json.loads(raw)
    except Exception:
        return None


def set_job(session_id: str, data: dict[str, Any]) -> None:
    """Write job state; paths stored as strings."""
    c = _client()
    if not c:
        return
    try:
        # Path objects -> str for JSON
        out = {}
        for k, v in data.items():
            if hasattr(v, "__fspath__"):
                out[k] = str(v)
            elif isinstance(v, Path):
                out[k] = str(v)
            else:
                out[k] = v
        c.set(REDIS_KEY_JOB.format(session_id), json.dumps(out), ex=REDIS_TTL_JOB)
    except Exception:
        pass


def publish_progress(session_id: str, payload: dict[str, Any]) -> None:
    """Publish progress event for Socket.IO (phase, current_segment, total_segments, message)."""
    c = _client()
    if not c:
        return
    try:
        c.publish(REDIS_CHAN_PROGRESS.format(session_id), json.dumps(payload))
    except Exception:
        pass


def get_admin_config_json() -> Optional[str]:
    """Raw JSON of admin config from Redis (for workers to read DJ rules without restart)."""
    c = _client()
    if not c:
        return None
    try:
        return c.get(REDIS_KEY_ADMIN_CONFIG)
    except Exception:
        return None


def set_admin_config_json(data: str) -> None:
    """Write full admin config JSON to Redis."""
    c = _client()
    if not c:
        return
    try:
        c.set(REDIS_KEY_ADMIN_CONFIG, data)
    except Exception:
        pass
