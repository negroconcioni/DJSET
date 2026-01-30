# Gateway API: FastAPI + Socket.IO, frontend estático
# Build desde raíz: docker compose build api
# Base Bookworm: más pesada pero con herramientas de compilación y repos Debian
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
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

COPY backend /app/backend
COPY frontend /app/frontend

WORKDIR /app/backend
ENV PYTHONPATH=/app/backend

EXPOSE 8000
CMD ["uvicorn", "app.main:asgi_app", "--host", "0.0.0.0", "--port", "8000"]
