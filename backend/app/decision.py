"""Mix decision: DJ brain (LLM or deterministic heuristics). OPUS-QUAD mental model. No audio processing."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from openai import OpenAI

from .admin_config import (
    get_allow_instruments_ai,
    get_allow_vocals_ai,
    get_bass_swap_intensity,
    get_default_bars,
    get_mix_sensitivity,
    get_system_prompt,
)
from .analysis import harmonic_distance_camelot
from .sample_library import get_compatible_samples
from .config import settings
from .models import MixStrategy, SongAnalysis

# ---------------------------------------------------------------------------
# Musical analysis helpers (bars ↔ seconds, energy scale)
# ---------------------------------------------------------------------------

BEATS_PER_BAR = 4


def bars_to_seconds(bpm: float, bars: int, beats_per_bar: int = BEATS_PER_BAR) -> float:
    """Convert bars to seconds using BPM. Deterministic and testable."""
    if bpm <= 0 or bars <= 0:
        return 0.0
    beats = bars * beats_per_bar
    return (beats / bpm) * 60.0


def energy_0_1_to_1_10(energy: float) -> int:
    """Convert raw energy 0-1 to DJ scale 1-10. Deterministic."""
    e = max(0.0, min(1.0, float(energy)))
    return max(1, min(10, round(e * 9 + 1)))


# ---------------------------------------------------------------------------
# DJ style prompt → intent (deterministic)
# ---------------------------------------------------------------------------


@dataclass
class DJIntent:
    """Parsed intent from dj_style_prompt. Affects transition length and timing."""

    preferred_transition_bars: int  # 4, 8, 16, 32, or 64
    vibe: str  # "subtle" | "aggressive" | "emotional" | "neutral" | "cattaneo" | "anyma"
    start_early: bool
    decisive: bool


def style_prompt_to_intent(dj_style_prompt: Optional[str]) -> DJIntent:
    """
    Map free-text DJ style prompt to structured intent.
    Deterministic keyword-based logic. No LLM.
    """
    if not dj_style_prompt or not dj_style_prompt.strip():
        default_bars = get_default_bars()
        return DJIntent(
            preferred_transition_bars=default_bars,
            vibe="neutral",
            start_early=False,
            decisive=False,
        )

    text = dj_style_prompt.lower().strip()
    # Perfiles de artista: Cattaneo → 64 barras, Progressive Outros
    cattaneo = any(x in text for x in ("cattaneo", "progressive", "progresivo", "prog"))
    # Anyma → cortes dinámicos 16 barras
    anyma = any(x in text for x in ("anyma", "dinámico", "dinamico"))
    # Closing / late night → decisive, shorter
    closing = any(
        x in text
        for x in ("closing", "5am", "5 am", "end of night", "last track", "finish")
    )
    # Warm-up / sunset / opening → long, subtle
    warmup = any(
        x in text
        for x in (
            "warm-up",
            "warm up",
            "sunset",
            "opening",
            "early",
            "chill",
            "ambient",
        )
    )
    # Emotional / nostalgic
    emotional = any(
        x in text for x in ("emotional", "nostalgic", "melancholic", "mixed-age")
    )
    # High energy / peak
    aggressive = any(
        x in text
        for x in ("peak", "energy", "club", "party", "drop", "aggressive")
    )

    if cattaneo:
        return DJIntent(
            preferred_transition_bars=64,
            vibe="cattaneo",
            start_early=True,
            decisive=False,
        )
    if anyma:
        return DJIntent(
            preferred_transition_bars=16,
            vibe="anyma",
            start_early=False,
            decisive=True,
        )
    if closing:
        return DJIntent(
            preferred_transition_bars=8,
            vibe="neutral",
            start_early=False,
            decisive=True,
        )
    if warmup:
        return DJIntent(
            preferred_transition_bars=16,
            vibe="subtle",
            start_early=True,
            decisive=False,
        )
    if emotional:
        return DJIntent(
            preferred_transition_bars=16,
            vibe="emotional",
            start_early=True,
            decisive=False,
        )
    if aggressive:
        return DJIntent(
            preferred_transition_bars=4,
            vibe="aggressive",
            start_early=False,
            decisive=True,
        )

    return DJIntent(
        preferred_transition_bars=8,
        vibe="neutral",
        start_early=False,
        decisive=False,
    )


# ---------------------------------------------------------------------------
# DJ personality log (console)
# ---------------------------------------------------------------------------

def log_dj_reasoning(strategy: MixStrategy, session_label: str = "mix") -> None:
    """Print DJ reasoning and dj_comment to console (DJ console style)."""
    r = (strategy.reasoning or "").strip()
    c = (getattr(strategy, "dj_comment", None) or "").strip()
    if not r and not c:
        return
    lines = ["", "   ─── DJ BRAIN (" + session_label + ") ───"]
    if c:
        lines.append("   💬 " + c.replace("\n", "\n   "))
    if r:
        lines.append("   " + r.replace("\n", "\n   "))
    lines.extend(["   ─────────────────────────────", ""])
    print("\n".join(lines), file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Format track structure (segments) for LLM context
# ---------------------------------------------------------------------------

def _format_audio_metadata_for_llm(metadata: Optional[dict[str, Any]], label: str) -> str:
    """Formatea BPM, duración y picos de energía para el prompt del LLM."""
    if not metadata:
        return f"{label}: (no metadata)"
    bpm = metadata.get("bpm", 0)
    duration = metadata.get("duration", 0)
    peaks = metadata.get("energy_peaks", [])
    peaks_str = ", ".join(f"{t}s" for t in peaks[:20]) if peaks else "ninguno"
    if len(peaks) > 20:
        peaks_str += f" … (+{len(peaks) - 20} más)"
    return f"{label}: BPM={bpm}, duration={duration}s, energy_peaks=[{peaks_str}]"


def _format_structure_for_llm(structure: Optional[dict[str, Any]], label: str) -> str:
    """Formatea metadata técnica: duración y puntos de alta/baja energía (segments)."""
    if not structure or not structure.get("segments"):
        return f"{label}: (no segment structure)"
    dur = structure.get("duration_sec", 0)
    segs = structure.get("segments", [])
    parts = [f"{label}: duration={dur:.1f}s, segments (start_sec–end_sec, energy):"]
    for s in segs[-12:]:  # últimos 12 segmentos (zona final + outro)
        parts.append(f"  {s.get('start_sec', 0):.0f}-{s.get('end_sec', 0):.0f}s {s.get('energy_level', 'mid')}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Pioneer Opus-Quad Simulator — System Prompt (perfiles, análisis, fx_chain)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Eres un motor de decisión que aplica las reglas de oro del DJing profesional. No imitás a nadie: aplicás análisis de segmentación, EQ dinámico y armonía universal.

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
- Mids (medios): cruce suave en toda la transición para que vocales/sintetizadores no choquen (crossfade constante).
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
"""


def _analysis_to_text(a: SongAnalysis, label: str) -> str:
    """Format analysis for LLM: BPM, key (readable + Camelot), energy 1-10, duration."""
    energy_10 = energy_0_1_to_1_10(a.energy)
    key_readable = f"{a.key} {a.key_scale}"
    camelot = getattr(a, "key_camelot", None) or ""
    parts = [
        f"{label}: BPM={a.bpm:.1f}, key={key_readable}" + (f" (Camelot {camelot})" if camelot else "") + f", energy={energy_10}/10, duration={a.duration_sec:.1f}s, beats={len(a.beats)}",
    ]
    if getattr(a, "genre", None):
        parts.append(f"genre={a.genre}")
    if getattr(a, "vibe", None):
        parts.append(f"vibe={a.vibe}")
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Validate and clamp LLM output (defensive)
# ---------------------------------------------------------------------------

def _clamp_strategy(data: dict, analysis_a: SongAnalysis, analysis_b: SongAnalysis) -> dict:
    """Clamp all values. Robustez FFmpeg: la transición NUNCA puede ser más larga que el track disponible."""
    out = dict(data)
    dur_a = analysis_a.duration_sec
    dur_b = analysis_b.duration_sec

    ta = float(out.get("song_a_transition_start_sec", 0.0))
    ta = max(0.0, min(ta, dur_a - 1.0))
    phrase_starts_a = getattr(analysis_a, "phrase_starts_sec", None) or []
    _outro_a = getattr(analysis_a, "outro_start_sec", None)
    outro_a = (dur_a - 60.0) if _outro_a is None else float(_outro_a)
    if phrase_starts_a:
        valid_phrases = [p for p in phrase_starts_a if p <= dur_a - 1.0 and p >= outro_a - 30]
        if valid_phrases:
            nearest = min(valid_phrases, key=lambda p: abs(p - ta))
            ta = nearest  # Obligatorio: alinear con phrase_starts_sec (32 compases)
    out["song_a_transition_start_sec"] = round(ta, 2)

    # Tiempo disponible en A para el fade (overlap nativo: no pedir más de lo que hay)
    remaining_a = max(0.5, dur_a - ta - 1.0)
    cf = float(out.get("crossfade_sec", 8.0))
    cf = max(0.5, min(cf, remaining_a, dur_b - 0.5, 120.0))
    out["crossfade_sec"] = cf

    # stretch ratios: avoid extreme (OPUS-QUAD tempo sliders)
    for key in ("song_a_stretch_ratio", "song_b_stretch_ratio"):
        v = float(out.get(key, 1.0))
        out[key] = max(0.5, min(2.0, v))

    # pitch: -12 to 12
    for key in ("song_a_pitch_semitones", "song_b_pitch_semitones"):
        v = float(out.get(key, 0.0))
        out[key] = max(-12.0, min(12.0, v))

    # B always starts at 0
    out["song_b_transition_start_sec"] = 0.0

    # transition_type (incluye filter_fade para mezcla armónica)
    allowed = ("crossfade", "beat_match_crossfade", "drop_swap", "filter_fade")
    out["transition_type"] = out.get("transition_type") if out.get("transition_type") in allowed else "beat_match_crossfade"

    # optional bars (for display); allow 4, 8, 16, 32, 64 (Cattaneo)
    bars = out.get("transition_length_bars")
    if bars is not None:
        b = int(bars)
        out["transition_length_bars"] = b if b in (4, 8, 16, 32, 64) else 8

    # start_offset_bars: 0–16 (intro skip on Track B)
    so = out.get("start_offset_bars", 0)
    try:
        so = int(so)
    except (TypeError, ValueError):
        so = 0
    out["start_offset_bars"] = max(0, min(16, so))

    out["reasoning"] = (out.get("reasoning") or "").strip() or "Transición elegida según análisis y estilo."
    out["dj_comment"] = (out.get("dj_comment") or "").strip() or None
    out["fx_chain"] = (out.get("fx_chain") or "").strip() or None

    # bass_swap_sec / bass_swap_point: mismo valor; Agresividad de la Mezcla (admin) define qué tan rápido el swap
    cf = float(out.get("crossfade_sec", 8.0))
    bsp = out.get("bass_swap_sec") or out.get("bass_swap_point")
    aggressiveness = get_bass_swap_intensity()  # 0 = swap tarde, 1 = swap temprano (más agresivo)
    default_ratio = 0.8 - 0.6 * aggressiveness  # 0.8 (tarde) a 0.2 (temprano)
    if bsp is not None:
        try:
            bsp = max(0.0, min(float(bsp), cf * 0.95))
        except (TypeError, ValueError):
            bsp = cf * default_ratio
    else:
        bsp = cf * default_ratio
    bsp = round(bsp, 2)
    out["bass_swap_point"] = bsp
    out["bass_swap_sec"] = bsp

    # filter_type
    ft = (out.get("filter_type") or "").strip() or "high-pass fade"
    out["filter_type"] = ft

    return out


# ---------------------------------------------------------------------------
# Deterministic DJ heuristics (no API key)
# ---------------------------------------------------------------------------

def _heuristic_strategy(
    analysis_a: SongAnalysis,
    analysis_b: SongAnalysis,
    intent: DJIntent,
) -> MixStrategy:
    """
    Human DJ heuristics as on an OPUS-QUAD.
    BPM diff < 5 → beatmatch; energy jump > 3 → shorter, decisive; style prompt affects bars.
    """
    bpm_a, bpm_b = analysis_a.bpm, analysis_b.bpm
    bpm_diff = abs(bpm_a - bpm_b) if bpm_b > 0 else 999
    energy_a_10 = energy_0_1_to_1_10(analysis_a.energy)
    energy_b_10 = energy_0_1_to_1_10(analysis_b.energy)
    energy_jump = abs(energy_a_10 - energy_b_10)

    avg_bpm = (bpm_a + bpm_b) / 2.0 if bpm_b > 0 else bpm_a
    bars = intent.preferred_transition_bars
    if bars > 32:
        bars = min(bars, 64)

    # Energy jump > 3 → shorter, decisive transition
    if energy_jump > 3:
        bars = min(bars, 8)
        decisive_energy = True
    else:
        decisive_energy = False

    crossfade_sec = bars_to_seconds(avg_bpm, bars)
    # Robustez: nunca más largo que el track disponible
    max_cf_a = max(0.5, analysis_a.duration_sec - 1.0)
    max_cf_b = max(0.5, analysis_b.duration_sec - 1.0)
    crossfade_sec = max(0.5, min(crossfade_sec, max_cf_a, max_cf_b, 120.0))
    if intent.decisive or decisive_energy:
        crossfade_sec = min(crossfade_sec, bars_to_seconds(avg_bpm, 8))

    if bpm_diff < 5 and bpm_b > 0:
        transition_type = "beat_match_crossfade"
        ratio_b = max(0.9, min(1.1, bpm_a / bpm_b))
        ratio_a = 1.0
    else:
        transition_type = "crossfade"
        ratio_a, ratio_b = 1.0, 1.0

    bars_before_end = 16 if intent.start_early else 8
    sec_before_end = bars_to_seconds(bpm_a, bars_before_end)
    transition_start_a = max(0.0, analysis_a.duration_sec - sec_before_end - crossfade_sec * 0.5)
    transition_start_a = min(transition_start_a, analysis_a.duration_sec - crossfade_sec - 0.5)
    transition_start_a = max(0.0, transition_start_a)
    phrase_starts_a = getattr(analysis_a, "phrase_starts_sec", None) or []
    outro_a = getattr(analysis_a, "outro_start_sec", None) or (analysis_a.duration_sec - 60.0)
    if phrase_starts_a:
        valid = [p for p in phrase_starts_a if p <= analysis_a.duration_sec - 1.0 and p >= outro_a - 30]
        if valid:
            nearest = min(valid, key=lambda p: abs(p - transition_start_a))
            if abs(nearest - transition_start_a) <= 15.0:
                transition_start_a = nearest

    remaining_a = max(0.5, analysis_a.duration_sec - transition_start_a - 0.5)
    crossfade_sec = min(crossfade_sec, remaining_a)
    crossfade_sec = max(0.5, crossfade_sec)

    camelot_a = getattr(analysis_a, "key_camelot", None) or ""
    camelot_b = getattr(analysis_b, "key_camelot", None) or ""
    harmonic_dist = harmonic_distance_camelot(camelot_a, camelot_b)
    transition_style = "long_atmospheric" if harmonic_dist <= 1 else ("short_rhythmic" if bars <= 8 else "wash_out")

    aggressiveness = get_bass_swap_intensity()
    default_ratio = 0.8 - 0.6 * aggressiveness
    bass_swap_point = round(crossfade_sec * default_ratio, 2)
    bass_swap_bars = max(1, round(bass_swap_point / (60.0 / bpm_a * 4)))

    reasoning = (
        f"Transición de {bars} barras ({crossfade_sec:.1f}s), {transition_type}. "
        f"Distancia armónica: {harmonic_dist}. Vibe: {intent.vibe}."
    )
    if energy_jump > 3:
        reasoning += f" Salto de energía alto → transición más corta."

    dj_comment = (
        f"Mezcla armónica detectada (distancia Camelot {harmonic_dist}). "
        f"Ejecutando Bass-Swap en el compás {bass_swap_bars} para evitar saturación de sub-frecuencias. "
        f"Mids en cruce suave; highs en fade progresivo."
    )
    if intent.vibe == "cattaneo":
        dj_comment = "Mezcla armónica detectada. Transición progresiva de 64 barras; Bass-Swap en compás 16 para evitar saturación de sub-frecuencias."
    elif intent.vibe == "anyma":
        dj_comment = "Corte dinámico de 16 barras. Bass-Swap en compás 8 para mantener la tensión sin saturar bajos."

    fx_chain = "Low: swap en bass_swap_sec; Mids: cruce suave; Highs: fade progresivo. High-pass en B que se abre en bass_swap."

    return MixStrategy(
        transition_type=transition_type,
        crossfade_sec=crossfade_sec,
        bass_swap_point=bass_swap_point,
        bass_swap_sec=bass_swap_point,
        filter_type="high-pass fade",
        harmonic_distance=harmonic_dist,
        transition_style=transition_style,
        song_a_stretch_ratio=ratio_a,
        song_a_pitch_semitones=0.0,
        song_a_transition_start_sec=max(0.0, transition_start_a),
        song_b_stretch_ratio=ratio_b,
        song_b_pitch_semitones=0.0,
        song_b_transition_start_sec=0.0,
        reasoning=reasoning,
        transition_length_bars=bars,
        start_offset_bars=0,
        dj_comment=dj_comment,
        fx_chain=fx_chain,
    )


# ---------------------------------------------------------------------------
# LLM as DJ brain (API key present)
# ---------------------------------------------------------------------------

def get_mix_strategy(
    analysis_a: SongAnalysis,
    analysis_b: SongAnalysis,
    dj_style_prompt: Optional[str] = None,
    audio_metadata_a: Optional[dict[str, Any]] = None,
    audio_metadata_b: Optional[dict[str, Any]] = None,
    track_structure_a: Optional[dict[str, Any]] = None,
    track_structure_b: Optional[dict[str, Any]] = None,
    compatible_overlays: Optional[list[tuple[Path, dict]]] = None,
    available_assets: Optional[dict[str, list[str]]] = None,
    cloud_compatible_overlays: Optional[list[dict[str, Any]]] = None,
    only_two_songs: bool = False,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> MixStrategy:
    """
    Decide transition strategy: LLM (if API key) o heurísticas.
    audio_metadata_a/b: dict con bpm, duration, energy_peaks (desde get_audio_metadata).
    compatible_overlays: si el Sequencer ya llamó a get_compatible_samples, pasá la lista aquí; si no, se calcula dentro.
    available_assets: resultado del scanner (instruments, vocals); el Sequencer lo pasa antes de pedir la decisión al LLM.
    cloud_compatible_overlays: samples por URL (cloud_assets); el Sequencer pasa los compatibles con BPM/Key para que la IA elija.
    """
    intent = style_prompt_to_intent(dj_style_prompt)
    api_key = api_key or settings.openai_api_key
    base_url = base_url or settings.openai_base_url
    client = OpenAI(api_key=api_key, base_url=base_url) if api_key else None

    if not client:
        strategy = _heuristic_strategy(analysis_a, analysis_b, intent)
        log_dj_reasoning(strategy, "heuristic")
        return strategy

    energy_a_10 = energy_0_1_to_1_10(analysis_a.energy)
    energy_b_10 = energy_0_1_to_1_10(analysis_b.energy)
    energy_jump = abs(energy_a_10 - energy_b_10)
    camelot_a = getattr(analysis_a, "key_camelot", None) or ""
    camelot_b = getattr(analysis_b, "key_camelot", None) or ""
    harmonic_dist = harmonic_distance_camelot(camelot_a, camelot_b)
    phrase_a = getattr(analysis_a, "phrase_starts_sec", None) or []
    phrase_b = getattr(analysis_b, "phrase_starts_sec", None) or []
    _outro_a = getattr(analysis_a, "outro_start_sec", None)
    outro_a = max(0.0, analysis_a.duration_sec - 60.0) if _outro_a is None else float(_outro_a)

    user_content = "Datos técnicos (BPM, Key, Camelot, energía):\n"
    user_content += _format_audio_metadata_for_llm(audio_metadata_a, "Track A (outgoing)") + "\n"
    user_content += _format_audio_metadata_for_llm(audio_metadata_b, "Track B (incoming)") + "\n\n"
    user_content += f"Energy: A={energy_a_10}/10, B={energy_b_10}/10 (jump={energy_jump}). "
    user_content += f"Distancia armónica Camelot: {harmonic_dist} (0=mismo, 1=vecino, 2+=lejano). "
    sens = get_mix_sensitivity()
    user_content += "Config: priorizar BPM/tempo." if sens < 0.4 else ("Config: priorizar armonía/key." if sens > 0.6 else "Config: equilibrio BPM y armonía.")
    user_content += "\n\n"
    user_content += f"Track A: phrase_starts_sec (inicios de frase cada 32 compases) = {phrase_a[-8:] if len(phrase_a) > 8 else phrase_a}. outro_start_sec = {outro_a:.0f}s.\n"
    user_content += f"Track B: phrase_starts_sec = {phrase_b[:8]}.\n\n"
    user_content += "Tarea: song_a_transition_start_sec debe alinearse OBLIGATORIAMENTE con un valor de phrase_starts_sec (múltiplos de 32 compases); si no, con la zona de outro de A (>= outro_start_sec). "
    user_content += "start_offset_bars debe hacer que B entre en inicio de frase. "
    if harmonic_dist <= 1:
        user_content += "Distancia armónica 0 o 1: priorizá transición larga y atmosférica (32–64 barras). "
    else:
        user_content += "Distancia armónica > 1: priorizá transición corta/rítmica o filter_fade/wash_out. "
    user_content += "Devuelve bass_swap_sec (segundo donde se cruzan los bajos; ej. crossfade_sec*0.5). "
    user_content += "dj_comment DEBE ser explicación técnica senior: ej. 'Mezcla armónica detectada. Ejecutando Bass-Swap en el compás 16 para evitar saturación de sub-frecuencias.'\n"
    if energy_jump > 3:
        user_content += "Salto de energía alto → transición más corta (4 u 8 barras). "
    user_content += "\nOutput ONLY the JSON object, no markdown."

    if track_structure_a or track_structure_b:
        user_content = "Segmentos de energía:\n" + _format_structure_for_llm(track_structure_a, "Track A") + "\n" + _format_structure_for_llm(track_structure_b, "Track B") + "\n\n" + user_content
    if dj_style_prompt and dj_style_prompt.strip():
        user_content = "Prompt del usuario: " + dj_style_prompt.strip() + "\n\n" + user_content

    # Sampler Manager: usar lista precalculada (Sequencer) o llamar get_compatible_samples aquí
    overlay_paths_resolved: list[Path] = []
    if compatible_overlays is None:
        compatible_overlays = []
        allow_instruments = get_allow_instruments_ai()
        allow_vocals = get_allow_vocals_ai()
        if allow_instruments or allow_vocals:
            avg_bpm = (analysis_a.bpm + analysis_b.bpm) / 2.0
            camelot_mix = camelot_a or camelot_b or "8A"
            categories = ["instruments"] if allow_instruments else []
            if allow_vocals:
                categories.append("vocals")
            compatible_overlays = get_compatible_samples(
                avg_bpm, camelot_mix, categories, bpm_tolerance=5.0, max_camelot_distance=1
            )
    if available_assets:
        user_content += "\n\nSampler (Opus Quad) — Tenés estos recursos:\n"
        user_content += "  instruments: " + (", ".join(available_assets.get("instruments", [])) or "(ninguno)") + "\n"
        user_content += "  vocals: " + (", ".join(available_assets.get("vocals", [])) or "(ninguno)") + "\n"
        user_content += "Si el reasoning indica baja energía, ELEGÍ uno de cada categoría (overlay_instrument, overlay_vocal con el filename). Si no, podés devolver null.\n"
        user_content += "Devuelve overlay_instrument: filename o null, overlay_vocal: filename o null.\n"
        user_content += "El punto donde entra el overlay debe coincidir con un inicio de frase (phrase_starts_sec); se usará el mismo que song_a_transition_start_sec.\n"
    if compatible_overlays:
        low_energy = energy_a_10 <= 4 or energy_b_10 <= 4
        harmonic_transition = harmonic_dist <= 1
        user_content += "\nSamples compatibles (BPM/Key) para elegir: "
        for path, meta in compatible_overlays[:12]:
            user_content += f"{path.name} (BPM={meta.get('bpm')}, {meta.get('key_camelot')}, {meta.get('category', '')}); "
        user_content += "\n"
    if cloud_compatible_overlays:
        by_cat: dict[str, list[dict]] = {}
        for e in cloud_compatible_overlays:
            cat = (e.get("category") or "").strip().lower()
            if cat not in by_cat:
                by_cat[cat] = []
            by_cat[cat].append(e)
        user_content += "\n\nCloud Sampler (JSON) — Tenés estos samples por URL:\n"
        for cat in ("instruments", "vocals"):
            entries = by_cat.get(cat, [])
            if not entries:
                continue
            user_content += f"  {cat}: "
            user_content += "; ".join(f"{e.get('url', '')} (name={e.get('name')}, BPM={e.get('bpm')}, key={e.get('key', '')})" for e in entries[:10])
            user_content += "\n"
        if only_two_songs:
            user_content += "Remix Live (OBLIGATORIO): Con solo 2 canciones el set debe ser un 'Remix Live'. DEBÉS elegir OBLIGATORIAMENTE al menos 2 samples de la nube: 1 instrumento (overlay_instrument_url) y 1 vocal (overlay_vocal_url) con las URL exactas del JSON. Sin excepción.\n"
        user_content += "Si el reasoning indica baja energía (o solo 2 canciones), ELEGÍ una URL de instrument y una de vocal (overlay_instrument_url, overlay_vocal_url). Si no, podés devolver null.\n"
        user_content += "Devuelve overlay_instrument_url: URL exacta o null, overlay_vocal_url: URL exacta o null.\n"

    system_prompt = get_system_prompt()
    response = client.chat.completions.create(
        model=settings.mix_decision_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.2,
    )

    text = response.choices[0].message.content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    data = json.loads(text)

    data["harmonic_distance"] = harmonic_dist
    data["transition_style"] = "long_atmospheric" if harmonic_dist <= 1 else ("wash_out" if data.get("transition_type") == "filter_fade" else "short_rhythmic")

    bars = data.get("transition_length_bars")
    if bars in (4, 8, 16, 32, 64):
        avg_bpm = (analysis_a.bpm + analysis_b.bpm) / 2.0
        data["crossfade_sec"] = max(0.5, min(120.0, bars_to_seconds(avg_bpm, bars)))
    data["song_b_transition_start_sec"] = 0.0

    data = _clamp_strategy(data, analysis_a, analysis_b)

    # Resolver overlay_instrument / overlay_vocal a paths; lógica forzada si energía baja o armónica 0–1
    overlay_paths_resolved: list[Path] = []
    overlay_bpms_resolved: list[float] = []
    if compatible_overlays:
        by_name = {p.name: (p, meta) for p, meta in compatible_overlays}
        for key in ("overlay_instrument", "overlay_vocal"):
            name = data.get(key)
            if name and isinstance(name, str):
                name = name.strip()
            if name and name in by_name:
                path, meta = by_name[name]
                overlay_paths_resolved.append(path)
                overlay_bpms_resolved.append(float(meta.get("bpm", 120.0)))
                data[key] = name
            elif name:
                data.pop(key, None)  # remove unresolved filename so strategy only has overlays we actually use
        # Si energía baja o armónica 0–1 y la IA devolvió null en ambos, forzar al menos un overlay
        low_energy = energy_a_10 <= 4 or energy_b_10 <= 4
        harmonic_transition = harmonic_dist <= 1
        if (low_energy or harmonic_transition) and not overlay_paths_resolved and compatible_overlays:
            path, meta = compatible_overlays[0]
            overlay_paths_resolved.append(path)
            overlay_bpms_resolved.append(float(meta.get("bpm", 120.0)))
        data["overlay_paths"] = overlay_paths_resolved if overlay_paths_resolved else None
        data["overlay_bpms"] = overlay_bpms_resolved if overlay_bpms_resolved else None
        # overlay_entry_sec: alinear al inicio de frase (phrase_starts_sec) más cercano a song_a_transition_start_sec
        ta = float(data.get("song_a_transition_start_sec", 0.0))
        phrase_starts_a = getattr(analysis_a, "phrase_starts_sec", None) or []
        if phrase_starts_a and overlay_paths_resolved:
            nearest = min(phrase_starts_a, key=lambda p: abs(p - ta))
            data["overlay_entry_sec"] = round(nearest, 2)
        else:
            data["overlay_entry_sec"] = round(ta, 2) if overlay_paths_resolved else None
    else:
        data["overlay_paths"] = None
        data["overlay_bpms"] = None
        data["overlay_entry_sec"] = None

    # Regla de Oro: si solo 2 canciones, forzar un instrumento y una vocal del JSON para rellenar el breakdown.
    if only_two_songs and cloud_compatible_overlays:
        by_cat_force: dict[str, list[dict]] = {}
        for e in cloud_compatible_overlays:
            cat = (e.get("category") or "").strip().lower()
            if cat not in by_cat_force:
                by_cat_force[cat] = []
            by_cat_force[cat].append(e)
        if not data.get("overlay_instrument_url") and by_cat_force.get("instruments"):
            first = by_cat_force["instruments"][0]
            data["overlay_instrument_url"] = first.get("url", "").strip()
            data["overlay_instrument_bpm"] = float(first.get("bpm", 120))
        if not data.get("overlay_vocal_url") and by_cat_force.get("vocals"):
            first = by_cat_force["vocals"][0]
            data["overlay_vocal_url"] = first.get("url", "").strip()
            data["overlay_vocal_bpm"] = float(first.get("bpm", 120))

    # Cloud: resolver overlay_instrument_url / overlay_vocal_url → overlay_instrument_bpm, overlay_vocal_bpm, overlay_entry_sec
    # Remove unvalidated URLs (not in cloud_compatible_overlays) so render_mix doesn't try to download them.
    if cloud_compatible_overlays and (data.get("overlay_instrument_url") or data.get("overlay_vocal_url")):
        by_url = {str(e.get("url", "")).strip(): e for e in cloud_compatible_overlays if e.get("url")}
        has_valid_cloud_overlay = False
        for key, bpm_key in [("overlay_instrument_url", "overlay_instrument_bpm"), ("overlay_vocal_url", "overlay_vocal_bpm")]:
            url_val = data.get(key)
            if url_val and isinstance(url_val, str):
                url_val = url_val.strip()
            if url_val and url_val in by_url:
                entry = by_url[url_val]
                data[bpm_key] = float(entry.get("bpm", 120))
                has_valid_cloud_overlay = True
            elif url_val:
                data.pop(key, None)
                data.pop(bpm_key, None)
        if has_valid_cloud_overlay:
            ta = float(data.get("song_a_transition_start_sec", 0.0))
            phrase_starts_a = getattr(analysis_a, "phrase_starts_sec", None) or []
            if phrase_starts_a:
                nearest = min(phrase_starts_a, key=lambda p: abs(p - ta))
                data["overlay_entry_sec"] = round(nearest, 2)
            else:
                data["overlay_entry_sec"] = round(ta, 2)

    strategy = MixStrategy(**data)
    log_dj_reasoning(strategy, "llm")
    return strategy
