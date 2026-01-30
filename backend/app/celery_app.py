"""Celery app: ai_brain queue (sequencer + strategy), audio_worker queue (render). Broker/backend = Redis."""
from celery import Celery
from .config import settings

broker = settings.redis_url or "redis://localhost:6379/0"
backend = settings.redis_url or "redis://localhost:6379/0"

app = Celery(
    "opus",
    broker=broker,
    backend=backend,
    include=["app.tasks"],
)
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_routes={
        "app.tasks.run_folder_pipeline": {"queue": "ai_brain"},
        "app.tasks.render_segment": {"queue": "audio_worker"},
        "app.tasks.finalize_set": {"queue": "ai_brain"},
    },
    task_default_queue="default",
    timezone="UTC",
    enable_utc=True,
)
