"""Mix decision: DJ brain (LLM or deterministic heuristics). OPUS-QUAD mental model. No audio processing."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from openai import OpenAI

from .config import settings
from .models import MixStrategy, SongAnalysis

# ---------------------------------------------------------------------------
# Musical analysis helpers (bars ↔ seconds)
# ---------------------------------------------------------------------------

BEATS_PER_BAR = 4


def bars_to_seconds(bpm: float, bars: int, beats_per_bar: int = BEATS_PER_BAR) -> float:
    """Convert bars to seconds using BPM. Deterministic and testable."""
    if bpm <= 0 or bars <= 0:
        return 0.0
    beats = bars * beats_per_bar
    return (beats / bpm) * 60.0


# ---------------------------------------------------------------------------
# DJ style prompt → intent (deterministic)
# ---------------------------------------------------------------------------


@dataclass
class DJIntent:
    """Parsed intent from dj_style_prompt. Affects transition length and timing."""

    preferred_transition_bars: int  # 4, 8, 16, or 32
    vibe: str  # "subtle" | "aggressive" | "emotional" | "neutral"
    start_early: bool  # True = longer overlap, start transition earlier
    decisive: bool  # True = shorter overlap, cleaner handoff (e.g. closing)


def style_prompt_to_intent(dj_style_prompt: Optional[str]) -> DJIntent:
    """
    Map free-text DJ style prompt to structured intent.
    Deterministic keyword-based logic. No LLM.
    """
    if not dj_style_prompt or not dj_style_prompt.strip():
        return DJIntent(
            preferred_transition_bars=8,
            vibe="neutral",
            start_early=False,
            decisive=False,
        )

    text = dj_style_prompt.lower().strip()
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
# OPUS-QUAD mental model: LLM system prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a human DJ mixing on a Pioneer DJ OPUS-QUAD. You output ONLY valid JSON.

HARDWARE MENTAL MODEL:
- Tempo is adjusted smoothly with tempo sliders; avoid extreme time-stretch (keep ratios near 1.0).
- Transitions use channel faders, not hard cuts.
- Basslines swap gradually (EQ); vocals managed by timing and EQ, not separation.
- You mix at phrase boundaries. Prefer 4, 8, 16, or 32 BAR transitions—never arbitrary seconds.
- Convert bars to seconds: seconds = (bars * 4 / BPM) * 60.

RULES:
- If BPM difference < 5: use beat_match_crossfade; match BPM with stretch_ratio (avoid ratios outside 0.9–1.1).
- Never stack two full choruses; prefer instrumental sections for the transition.
- High energy → shorter transition (4 or 8 bars). Warm-up / sunset → longer (16 or 32 bars). Closing set → decisive (8 bars).
- Only one vocal should lead at a time; avoid vocal clashes.
- song_b_transition_start_sec must be 0 (B starts when crossfade starts).

Output a single JSON object with exactly these fields (numbers as numbers):
- transition_type: one of "crossfade", "beat_match_crossfade", "drop_swap"
- transition_length_bars: 4, 8, 16, or 32
- crossfade_sec: float (MUST = (transition_length_bars * 4 / BPM) * 60, use average of A and B BPM; clamp to 0.5–32)
- song_a_stretch_ratio: float 0.5–2.0 (prefer 0.9–1.1 for beatmatch)
- song_a_pitch_semitones: float -12–12 (0 if keys compatible)
- song_a_transition_start_sec: float >= 0 (when to start fading A; e.g. N bars before end of A)
- song_b_stretch_ratio: float 0.5–2.0
- song_b_pitch_semitones: float -12–12
- song_b_transition_start_sec: 0.0
- reasoning: short explanation (human DJ style)
"""


def _analysis_to_text(a: SongAnalysis, label: str) -> str:
    return (
        f"{label}: BPM={a.bpm:.1f}, key={a.key} {a.key_scale}, "
        f"duration={a.duration_sec:.1f}s, energy={a.energy:.2f}, "
        f"beats_count={len(a.beats)}"
    )


# ---------------------------------------------------------------------------
# Validate and clamp LLM output (defensive)
# ---------------------------------------------------------------------------

def _clamp_strategy(data: dict, analysis_a: SongAnalysis, analysis_b: SongAnalysis) -> dict:
    """Clamp all values to valid ranges. Ensures OPUS-QUAD-safe output."""
    out = dict(data)

    # crossfade_sec: 0.5–32
    cf = float(out.get("crossfade_sec", 8.0))
    out["crossfade_sec"] = max(0.5, min(32.0, cf))

    # stretch ratios: avoid extreme (OPUS-QUAD tempo sliders)
    for key in ("song_a_stretch_ratio", "song_b_stretch_ratio"):
        v = float(out.get(key, 1.0))
        out[key] = max(0.5, min(2.0, v))

    # pitch: -12 to 12
    for key in ("song_a_pitch_semitones", "song_b_pitch_semitones"):
        v = float(out.get(key, 0.0))
        out[key] = max(-12.0, min(12.0, v))

    # transition start A: >= 0, and leave room for crossfade
    ta = float(out.get("song_a_transition_start_sec", 0.0))
    max_start_a = max(0.0, analysis_a.duration_sec - out["crossfade_sec"] - 1.0)
    out["song_a_transition_start_sec"] = max(0.0, min(ta, max_start_a))

    # B always starts at 0
    out["song_b_transition_start_sec"] = 0.0

    # transition_type
    allowed = ("crossfade", "beat_match_crossfade", "drop_swap")
    out["transition_type"] = out.get("transition_type") if out.get("transition_type") in allowed else "beat_match_crossfade"

    # optional bars (for display)
    bars = out.get("transition_length_bars")
    if bars is not None:
        b = int(bars)
        out["transition_length_bars"] = b if b in (4, 8, 16, 32) else 8

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
    BPM diff < 5 → beatmatch; style prompt affects bars and timing.
    """
    bpm_a, bpm_b = analysis_a.bpm, analysis_b.bpm
    bpm_diff = abs(bpm_a - bpm_b) if bpm_b > 0 else 999

    # Transition length in bars from intent; convert to seconds using average BPM
    avg_bpm = (bpm_a + bpm_b) / 2.0 if bpm_b > 0 else bpm_a
    bars = intent.preferred_transition_bars
    crossfade_sec = bars_to_seconds(avg_bpm, bars)
    crossfade_sec = max(0.5, min(32.0, crossfade_sec))

    # Shorter if decisive
    if intent.decisive:
        crossfade_sec = min(crossfade_sec, bars_to_seconds(avg_bpm, 8))

    # Transition type: beatmatch when BPM close
    if bpm_diff < 5 and bpm_b > 0:
        transition_type = "beat_match_crossfade"
        ratio_b = bpm_a / bpm_b
        ratio_b = max(0.9, min(1.1, ratio_b))  # avoid extreme stretch
        ratio_a = 1.0
    else:
        transition_type = "crossfade"
        ratio_a, ratio_b = 1.0, 1.0

    # When to start transition in A: N bars before end, or earlier if start_early
    bars_before_end = 16 if intent.start_early else 8
    sec_before_end = bars_to_seconds(bpm_a, bars_before_end)
    transition_start_a = max(0.0, analysis_a.duration_sec - sec_before_end - crossfade_sec * 0.5)
    transition_start_a = min(transition_start_a, analysis_a.duration_sec - crossfade_sec - 0.5)

    return MixStrategy(
        transition_type=transition_type,
        crossfade_sec=crossfade_sec,
        song_a_stretch_ratio=ratio_a,
        song_a_pitch_semitones=0.0,
        song_a_transition_start_sec=max(0.0, transition_start_a),
        song_b_stretch_ratio=ratio_b,
        song_b_pitch_semitones=0.0,
        song_b_transition_start_sec=0.0,
        reasoning=f"Heuristic: {transition_type}, {bars} bar transition ({crossfade_sec:.1f}s). {intent.vibe}.",
        transition_length_bars=bars,
    )


# ---------------------------------------------------------------------------
# LLM as DJ brain (API key present)
# ---------------------------------------------------------------------------

def get_mix_strategy(
    analysis_a: SongAnalysis,
    analysis_b: SongAnalysis,
    dj_style_prompt: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> MixStrategy:
    """
    Decide transition strategy: LLM (if API key) or deterministic heuristics.
    dj_style_prompt influences transition length and vibe. No audio processing.
    """
    intent = style_prompt_to_intent(dj_style_prompt)
    api_key = api_key or settings.openai_api_key
    base_url = base_url or settings.openai_base_url
    client = OpenAI(api_key=api_key, base_url=base_url) if api_key else None

    if not client:
        return _heuristic_strategy(analysis_a, analysis_b, intent)

    user_content = (
        "Song A (outgoing): " + _analysis_to_text(analysis_a, "A") + "\n"
        "Song B (incoming): " + _analysis_to_text(analysis_b, "B") + "\n"
    )
    if dj_style_prompt and dj_style_prompt.strip():
        user_content += "\nDJ style / context: " + dj_style_prompt.strip() + "\n"
    user_content += "\nOutput ONLY the JSON object, no markdown."

    response = client.chat.completions.create(
        model=settings.mix_decision_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.2,
    )

    text = response.choices[0].message.content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    data = json.loads(text)

    # Recompute crossfade_sec from bars if provided (LLM sometimes ignores formula)
    bars = data.get("transition_length_bars")
    if bars in (4, 8, 16, 32):
        avg_bpm = (analysis_a.bpm + analysis_b.bpm) / 2.0
        data["crossfade_sec"] = max(0.5, min(32.0, bars_to_seconds(avg_bpm, bars)))
    data["song_b_transition_start_sec"] = 0.0

    data = _clamp_strategy(data, analysis_a, analysis_b)
    return MixStrategy(**data)
