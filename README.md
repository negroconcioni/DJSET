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

Nota: `essentia` puede requerir compilación o wheels según la plataforma. Si falla, ver [Essentia install](https://essentia.upf.edu/installing.html).

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
| GET    | `/health` | Health check |

## Licencia

MVP interno / uso local.
