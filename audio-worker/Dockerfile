# Audio Worker: Celery worker cola audio_worker (FFmpeg, Rubber Band, processor, cloud sampler vía httpx)
# Build desde raíz: docker compose build audio-worker
# Stateless: descarga (httpx), mezcla, borra. Sin libessentia; análisis con librosa en ai-brain.
# Base Bookworm; acceso a red para cloud_assets.
FROM python:3.11-bookworm

# Herramientas básicas de compilación + librerías de audio (sin Essentia; análisis con librosa)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    pkg-config \
    libfftw3-dev \
    libtag1-dev \
    libsamplerate0-dev \
    ffmpeg \
    rubberband-cli \
    libavcodec-extra \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

COPY backend /app/backend

WORKDIR /app/backend
ENV PYTHONPATH=/app/backend

CMD ["celery", "-A", "app.celery_app", "worker", "-Q", "audio_worker", "-l", "info"]
