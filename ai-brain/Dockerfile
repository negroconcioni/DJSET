# AI Brain: Celery worker cola ai_brain (sequencer + decisión IA + finalize)
# Build desde raíz: docker compose build ai-brain
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    rubberband-cli \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend /app/backend

WORKDIR /app/backend
ENV PYTHONPATH=/app/backend

CMD ["celery", "-A", "app.celery_app", "worker", "-Q", "ai_brain", "-l", "info"]
