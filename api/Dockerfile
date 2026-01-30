# Gateway API: FastAPI + Socket.IO, frontend estático
# Build desde raíz: docker compose build api
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    rubberband-cli \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend /app/backend
COPY frontend /app/frontend

WORKDIR /app/backend
ENV PYTHONPATH=/app/backend

EXPOSE 8000
CMD ["uvicorn", "app.main:asgi_app", "--host", "0.0.0.0", "--port", "8000"]
