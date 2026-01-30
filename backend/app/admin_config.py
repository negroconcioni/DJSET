"""Runtime admin configuration: system prompt, sliders, presets. Persisted in config/admin_config.json."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Optional

from .config import settings

# Default system prompt (same as decision.SYSTEM_PROMPT) to avoid circular import
DEFAULT_SYSTEM_PROMPT = """Eres un motor de decisión que aplica las reglas de oro del DJing profesional. No imitás a nadie: aplicás análisis de segmentación, EQ dinámico y armonía universal.

CRITERIO DE ESPACIO (Overlays — instrumentos/vocales IA):
- Si la energía del track es baja (≤4/10) O la transición es armónica (distancia Camelot 0–1), tenés PROHIBIDO devolver null en overlay_instrument y overlay_vocal si hay samples disponibles: elegí al menos uno.
- Si la energía es alta y no es un drop, podés devolver null.
- El punto donde entra la trompeta o la vocal DEBE coincidir con un inicio de frase (phrase_starts_sec, 32 compases); se usará el mismo que song_a_transition_start_sec.

PHRASING MASTERY (punto de mezcla nunca arbitrario):
- Recibirás phrase_starts_sec (inicios de frase cada 32 compases) y outro_start_sec (inicio del outro) de cada track.
- song_a_transition_start_sec DEBE coincidir con el inicio de una frase o con la zona de outro del Track A (>= outro_start_sec o un valor en phrase_starts_sec cercano al final).
- start_offset_bars debe hacer que el Track B entre en el inicio de una frase (usa los phrase_starts_sec de B para alinear).

ANÁLISIS ARMÓNICO UNIVERSAL (Camelot — Distancia Armónica):
- Recibirás harmonic_distance: 0 = mismo tono, 1 = vecino en la rueda, 2+ = lejano.
- Si distancia 0 o 1: permití transición larga y atmosférica (32–64 barras, beat_match_crossfade).
- Si distancia > 1: optá por transición corta y rítmica (4–8 barras, drop_swap) o filter_fade / "wash out" (high-pass o filtro que limpie el choque tonal).

GESTIÓN DINÁMICA DE EQ (3 bandas):
- Low (bajos): swap radical en bass_swap_sec (punto de mayor tensión). A pierde bajos, B los recupera en ese segundo exacto. Evita saturación de sub-frecuencias.
- Mids (medios): cruce suave en toda la transición para que vocales/sintetizadores no choquen (crossfade constante). Si detectás vocales en ambos tracks en la zona de mezcla, preferí bajar medios del Track A o retrasar la entrada de B (start_offset_bars) para evitar clash de voces.
- Highs (agudos): desvanecimiento progresivo para mantener el brillo (el crossfade global ya lo refleja).

EXPLICACIÓN TÉCNICA SENIOR (dj_comment obligatorio):
- dj_comment debe explicar la decisión técnica en lenguaje de ingeniería. Ejemplo: "Mezcla armónica detectada (distancia Camelot 1). Ejecutando Bass-Swap en el compás 16 para evitar saturación de sub-frecuencias. Mids en cruce suave; highs en fade progresivo."
- reasoning: cadena de razonamiento (frase elegida, distancia armónica, por qué bass_swap en ese compás).

REGLAS DE ROBUSTEZ:
- crossfade_sec NUNCA mayor que el tiempo disponible. bass_swap_sec entre 0 y crossfade_sec (ej. crossfade_sec * 0.5).

Output ONLY a single JSON object (numbers as numbers):
- transition_type, transition_length_bars, crossfade_sec, bass_swap_sec, filter_type
- song_a_stretch_ratio, song_a_pitch_semitones, song_a_transition_start_sec (alineado a frase/outro)
- song_b_stretch_ratio, song_b_pitch_semitones, song_b_transition_start_sec: 0.0
- start_offset_bars (para que B entre en inicio de frase)
- reasoning, dj_comment (explicación técnica senior con compás de bass-swap y justificación armónica)
- fx_chain (Low: swap en bass_swap_sec; Mids: cruce suave; Highs: fade progresivo)
- overlay_instrument (filename o null), overlay_vocal (filename o null). Si energía baja o armónica 0–1 y hay samples, elegí al menos uno.
"""

_CONFIG_DIR: Optional[Path] = None
_CACHE: Optional[dict[str, Any]] = None


def _config_path() -> Path:
    global _CONFIG_DIR
    if _CONFIG_DIR is None:
        _CONFIG_DIR = settings.base_dir / "config"
    return _CONFIG_DIR / "admin_config.json"


def _default_config() -> dict[str, Any]:
    return {
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "mix_sensitivity": 0.5,
        "default_bars": 32,
        "bass_swap_intensity": 0.5,
        "presets": [],
        "allow_instruments_ai": False,
        "allow_vocals_ai": False,
    }


def _load_raw() -> dict[str, Any]:
    global _CACHE
    # Prefer Redis when configured (workers read DJ rules without restart)
    if settings.use_celery:
        try:
            from .redis_store import get_admin_config_json
            raw = get_admin_config_json()
            if raw:
                data = json.loads(raw)
                out = _default_config()
                out.update({k: v for k, v in data.items() if k in out})
                if "presets" in data and isinstance(data["presets"], list):
                    out["presets"] = list(data["presets"])
                _CACHE = out
                return _CACHE
        except Exception:
            pass
    path = _config_path()
    if not path.exists():
        _CACHE = _default_config()
        return _CACHE
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        out = _default_config()
        out.update({k: v for k, v in data.items() if k in out})
        if "presets" in data and isinstance(data["presets"], list):
            out["presets"] = list(data["presets"])
        _CACHE = out
        if settings.use_celery:
            try:
                from .redis_store import set_admin_config_json
                set_admin_config_json(json.dumps(out, ensure_ascii=False))
            except Exception:
                pass
        return _CACHE
    except Exception:
        _CACHE = _default_config()
        return _CACHE


def _save_raw(data: dict[str, Any]) -> None:
    global _CACHE
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    _CACHE = data
    # Mirror to Redis so workers pick up new DJ rules instantly
    if settings.use_celery:
        try:
            from .redis_store import set_admin_config_json
            set_admin_config_json(json.dumps(data, ensure_ascii=False))
        except Exception:
            pass


def get_admin_config() -> dict[str, Any]:
    """Return full admin config (mix_sensitivity, default_bars, bass_swap_intensity, presets, system_prompt)."""
    return _load_raw()


def get_system_prompt() -> str:
    """Return current system prompt for the DJ LLM (from admin config or default)."""
    cfg = _load_raw()
    return (cfg.get("system_prompt") or "").strip() or DEFAULT_SYSTEM_PROMPT


def get_mix_sensitivity() -> float:
    """0 = priorizar BPM, 1 = priorizar armonía. Clamped to [0, 1]."""
    cfg = _load_raw()
    v = float(cfg.get("mix_sensitivity", 0.5))
    return max(0.0, min(1.0, v))


def get_default_bars() -> int:
    """Default transition length in bars: 16, 32, or 64."""
    cfg = _load_raw()
    v = int(cfg.get("default_bars", 32))
    if v not in (16, 32, 64):
        return 32
    return v


def get_bass_swap_intensity() -> float:
    """How aggressive the bass swap filter is. 0 = soft, 1 = aggressive. [0, 1]."""
    cfg = _load_raw()
    v = float(cfg.get("bass_swap_intensity", 0.5))
    return max(0.0, min(1.0, v))


def get_allow_instruments_ai() -> bool:
    """Whether the AI may add instrument overlays from the sample library."""
    cfg = _load_raw()
    return bool(cfg.get("allow_instruments_ai", False))


def get_allow_vocals_ai() -> bool:
    """Whether the AI may add vocal overlays from the sample library."""
    cfg = _load_raw()
    return bool(cfg.get("allow_vocals_ai", False))


def get_presets() -> list[dict[str, Any]]:
    """List of presets: [{ id, name, params }, ...]."""
    cfg = _load_raw()
    presets = cfg.get("presets") or []
    return list(presets) if isinstance(presets, list) else []


def set_admin_config(
    *,
    system_prompt: Optional[str] = None,
    mix_sensitivity: Optional[float] = None,
    default_bars: Optional[int] = None,
    bass_swap_intensity: Optional[float] = None,
    presets: Optional[list[dict[str, Any]]] = None,
    allow_instruments_ai: Optional[bool] = None,
    allow_vocals_ai: Optional[bool] = None,
) -> dict[str, Any]:
    """Update admin config in memory and on disk. Omitted keys are left unchanged."""
    data = _load_raw()
    if system_prompt is not None:
        data["system_prompt"] = system_prompt
    if mix_sensitivity is not None:
        data["mix_sensitivity"] = max(0.0, min(1.0, float(mix_sensitivity)))
    if default_bars is not None:
        b = int(default_bars)
        data["default_bars"] = b if b in (16, 32, 64) else 32
    if bass_swap_intensity is not None:
        data["bass_swap_intensity"] = max(0.0, min(1.0, float(bass_swap_intensity)))
    if presets is not None:
        data["presets"] = [dict(p) for p in presets]
    if allow_instruments_ai is not None:
        data["allow_instruments_ai"] = bool(allow_instruments_ai)
    if allow_vocals_ai is not None:
        data["allow_vocals_ai"] = bool(allow_vocals_ai)
    _save_raw(data)
    return data


def add_preset(name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Append a preset; assign id if missing. Returns updated full config."""
    data = _load_raw()
    presets = list(data.get("presets") or [])
    preset = dict(params)
    preset["name"] = name
    if not preset.get("id"):
        preset["id"] = str(uuid.uuid4())[:8]
    presets.append(preset)
    data["presets"] = presets
    _save_raw(data)
    return data


def remove_preset(preset_id: str) -> dict[str, Any]:
    """Remove preset by id. Returns updated full config."""
    data = _load_raw()
    presets = [p for p in (data.get("presets") or []) if p.get("id") != preset_id]
    data["presets"] = presets
    _save_raw(data)
    return data
