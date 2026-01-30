# AutoMix AI — MVP

Aplicación que mezcla dos canciones de forma offline: analiza BPM, key, beats y energía; un LLM devuelve una estrategia en JSON; el motor de audio (Rubber Band + FFmpeg) genera un único archivo mezclado.

## Reglas del MVP

- Mezcla **offline**, no en tiempo real.
- Sin edición manual.
- El LLM **solo devuelve JSON** de decisión; no procesa audio.
- Motor de audio: time-stretch, pitch-shift y transición con **FFmpeg** y **Rubber Band**.

## Stack

- Python 3.11
- FastAPI
- librosa, Essentia (análisis)
- Rubber Band, FFmpeg (render)
- OpenAI-compatible API (solo para JSON de estrategia)

## Arquitectura del proyecto

```
DJSET/
├── backend/
│   └── app/
│       ├── __init__.py
│       ├── config.py      # Configuración (paths, API key, etc.)
│       ├── models.py      # SongAnalysis, MixStrategy (Pydantic)
│       ├── analysis.py    # Análisis musical (librosa + Essentia)
│       ├── decision.py    # Decisión de mezcla (LLM → JSON)
│       ├── render.py      # Motor de render (Rubber Band + FFmpeg)
│       └── main.py        # FastAPI: upload, generate, download
├── frontend/
│   └── index.html         # UI mínima: subir A/B, generar, descargar
├── requirements.txt
├── .env.example
└── README.md
```

Flujo: **Upload A/B** → **Analizar** (BPM, key, beats, energía) → **LLM** (estrategia JSON) → **Render** (time-stretch, pitch-shift, crossfade) → **Descargar** WAV.

## Requisitos del sistema

- **Python 3.11**
- **FFmpeg** (en PATH)
- **Rubber Band** (CLI `rubberband` en PATH)

### Instalar FFmpeg y Rubber Band

**macOS (Homebrew):**

```bash
brew install ffmpeg rubberband
```

**Ubuntu/Debian:**

```bash
sudo apt update
sudo apt install ffmpeg rubberband-cli
```

## Setup local

1. **Clonar / entrar al proyecto**

```bash
cd /ruta/a/DJSET
```

2. **Crear entorno virtual**

```bash
python3.11 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
```

3. **Instalar dependencias**

```bash
pip install -r requirements.txt
```

Análisis de audio (BPM, energía, tonalidad) se hace con Librosa; no se usa Essentia.

4. **Variables de entorno (opcional)**

Para que el LLM elija la estrategia, configurar API key de OpenAI (o compatible):

```bash
cp .env.example .env
# Editar .env y poner AUTOMIX_OPENAI_API_KEY=sk-...
```

Sin `AUTOMIX_OPENAI_API_KEY` se usa una estrategia por defecto (crossfade fijo).

5. **Ejecutar la aplicación**

Desde la **raíz del proyecto** (DJSET):

```bash
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

6. **Abrir en el navegador**

- Frontend: http://localhost:8000/
- API docs: http://localhost:8000/docs

## Uso

1. En http://localhost:8000/ subir **Song A** (salida) y **Song B** (entrada).
2. Pulsar **Generar mezcla**.
3. Cuando termine, usar **Descargar mezcla** para obtener el WAV mezclado.

Formatos de audio soportados para subida: WAV, MP3, FLAC, OGG, M4A (según FFmpeg/librosa).

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST   | `/session` | Crear sesión; devuelve `session_id` |
| POST   | `/upload/{session_id}/a` | Subir canción A (body: `file`) |
| POST   | `/upload/{session_id}/b` | Subir canción B (body: `file`) |
| POST   | `/generate/{session_id}` | Analizar, decidir estrategia, renderizar y devolver info + `download_url` |
| GET    | `/download/{session_id}` | Descargar el WAV mezclado |
| POST   | `/process-folder` | Subir múltiples tracks; encola pipeline (Sequencer + Audio worker) si Redis está configurado |
| GET    | `/process-folder/{session_id}/status` | Estado del set (phase, current_segment, total_segments) |
| GET    | `/process-folder/{session_id}/set` | Descargar WAV del set completo |
| GET    | `/process-folder/{session_id}/tracklist` | Descargar tracklist.txt |
| GET    | `/health` | Health check |

## Backend 100% Stateless

- **Directorio temporal por sesión**: cada sesión usa `session_root / session_id`; los archivos subidos y el WAV generado viven solo ahí. Se borra tras la descarga exitosa o por TTL.
- **Redis TTL 1h**: los metadatos de análisis (BPM, Key) y el estado del job viven en Redis con TTL 1 hora. Si el usuario no descarga, la información expira sola.
- **Streaming + borrado**: el set/mix se sirve como stream; tras la descarga exitosa se elimina el directorio de sesión.
- **Try/finally**: todo el pipeline de mezcla está envuelto en try/finally para garantizar que, si el proceso crashea, el directorio temporal se destruya.

### Purga inicial (una sola vez)

Antes de usar el backend stateless, podés limpiar los archivos antiguos en `uploads/` y `output/`:

```bash
# Desde la raíz del proyecto, con el venv activado
python scripts/purge_uploads_and_output.py
```

Elimina todos los `.mp3`, `.wav` y `.txt` en esas carpetas (usa `backend.app.config` para las rutas).

### Limpieza de sesiones abandonadas

`POST /cleanup` borra directorios de sesión cuyo job ya no está en Redis (TTL expirado). Podés llamarlo periódicamente o al arrancar.

## Microservicios (Redis + Celery)

Con `AUTOMIX_REDIS_URL` configurado (ej. `redis://localhost:6379/0`):

- **Admin config** se guarda en Redis; los workers leen las reglas de DJ sin reiniciar.
- **Process-folder** se encola en Celery: cola `ai_brain` (sequencer + estrategia por segmento) y cola `audio_worker` (render por segmento con hsin/loudnorm/amix).
- **Socket.IO**: los workers publican progreso en Redis; la API reenvía al frontend en tiempo real.

### Arrancar workers

Desde la raíz del proyecto (con Redis en marcha):

```bash
# Worker AI-brain (sequencer + estrategia + finalize)
celery -A backend.app.celery_app worker -Q ai_brain -l info

# Worker audio (render de cada segmento)
celery -A backend.app.celery_app worker -Q audio_worker -l info
```

O un solo worker que consuma ambas colas:

```bash
celery -A backend.app.celery_app worker -Q ai_brain,audio_worker -l info
```

### Arrancar API con Socket.IO

Para progreso en tiempo real, usar el ASGI app que monta Socket.IO:

```bash
uvicorn backend.app.main:asgi_app --reload --host 0.0.0.0 --port 8000
```

(Solo aplica cuando `AUTOMIX_REDIS_URL` está definido.)

## Docker (Opus Pro Infrastructure)

En la raíz del proyecto hay un `docker-compose.yml` que orquesta la API, los workers y Redis. La estructura de carpetas es:

```
DJSET/
├── api/              # Dockerfile para el gateway (FastAPI + frontend)
├── ai-brain/         # Dockerfile para el worker Celery cola ai_brain (sequencer + decisión IA)
├── audio-worker/     # Dockerfile para el worker Celery cola audio_worker (FFmpeg, processor)
├── shared_data/      # Volumen compartido: solo sesiones temporales (montado en /app/data)
│   └── sessions/     # session_root: se borra tras descarga o TTL
├── assets/           # Volumen compartido: samples para overlays IA (montado en /app/assets)
│   └── samples/
│       ├── percussion/
│       ├── instruments/
│       └── vocals/
├── backend/          # Código común (main.py, decision.py, sequencer.py, render.py, audio/processor.py, etc.)
├── frontend/         # index.html, admin.html, css/, js/, scss/
└── docker-compose.yml
```

Los Dockerfiles en `api/`, `ai-brain/` y `audio-worker/` se construyen con **contexto en la raíz** del proyecto (`context: .`), así que copian `backend/` y (solo api) `frontend/` sin duplicar código.

### Levantar todo con Docker

Desde la raíz del proyecto:

```bash
docker compose up --build
```

- **API**: http://localhost:8000
- **Redis**: localhost:6379 (para desarrollo; los workers se conectan por nombre `redis`)

Variables de entorno que el compose ya inyecta: `AUTOMIX_REDIS_URL`, `AUTOMIX_SESSION_ROOT=/app/data/sessions` (solo temporales), `AUTOMIX_ASSETS_SAMPLES_DIR=/app/assets/samples`. Para LLM, configurar en `.env` o en el compose: `AUTOMIX_OPENAI_API_KEY`.

### Organización lógica del código (sin mover archivos)

- **API** (`api/Dockerfile`): sirve `backend.app.main` (FastAPI + Socket.IO) y el frontend estático desde `/app/frontend`.
- **AI Brain**: ejecuta `celery -A app.celery_app worker -Q ai_brain` (sequencer, decisión por segmento, finalize); usa `backend/app/sequencer.py`, `decision.py`, `tasks.py`, etc.
- **Audio Worker**: ejecuta `celery -A app.celery_app worker -Q audio_worker` (render por segmento); usa `backend/app/render.py`, `backend/app/audio/processor.py`, etc.

Los samples para overlays IA van en `assets/samples/percussion`, `instruments` y `vocals` (o en `backend/assets/samples/` si corrés sin Docker); la IA los elige según BPM/Key cuando está habilitado en admin.

## Licencia

MVP interno / uso local.
