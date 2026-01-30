"""Pydantic models for API and LLM decision schema."""
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field


class SongAnalysis(BaseModel):
    """Result of musical analysis for one song."""

    bpm: float = Field(..., description="Beats per minute")
    key: str = Field(..., description="Musical key e.g. C major")
    key_scale: str = Field(default="major", description="major or minor")
    key_camelot: Optional[str] = Field(default=None, description="Camelot Wheel e.g. 8A, 1B for LLM")
    beats: list[float] = Field(default_factory=list, description="Beat times in seconds")
    energy: float = Field(..., ge=0, le=1, description="Overall energy 0-1 (raw); use energy_1_10 for display")
    duration_sec: float = Field(..., description="Duration in seconds")
    phrase_starts_sec: List[float] = Field(default_factory=list, description="Phrase boundaries every 32 bars (mix points)")
    outro_start_sec: float = Field(default=0.0, description="Start of outro/transition zone (last 2 phrases)")
    path: Optional[Path] = None
    genre: Optional[str] = Field(default=None, description="Genre if available")
    vibe: Optional[str] = Field(default=None, description="Vibe/mood if available")


class MixStrategy(BaseModel):
    """LLM output: strategy for the mix (JSON only)."""

    transition_type: str = Field(
        ...,
        description="One of: crossfade, beat_match_crossfade, drop_swap",
    )
    crossfade_sec: float = Field(
        ...,
        ge=0.5,
        le=120.0,
        description="Crossfade duration in seconds (clamped to available track in decision)",
    )
    # Song A (outgoing) adjustments
    song_a_stretch_ratio: float = Field(
        ...,
        ge=0.5,
        le=2.0,
        description="Time stretch ratio for song A at transition",
    )
    song_a_pitch_semitones: float = Field(
        ...,
        ge=-12,
        le=12,
        description="Pitch shift in semitones for song A at transition",
    )
    song_a_transition_start_sec: float = Field(
        ...,
        ge=0,
        description="When to start transition in song A (seconds)",
    )
    # Song B (incoming) adjustments
    song_b_stretch_ratio: float = Field(
        ...,
        ge=0.5,
        le=2.0,
        description="Time stretch ratio for song B at transition",
    )
    song_b_pitch_semitones: float = Field(
        ...,
        ge=-12,
        le=12,
        description="Pitch shift in semitones for song B at transition",
    )
    song_b_transition_start_sec: float = Field(
        ...,
        ge=0,
        description="When song B starts in the mix (seconds from mix start)",
    )
    reasoning: str = Field(
        default="",
        description="DJ reasoning: WHY these bars and this transition (chain-of-thought, musical logic).",
    )
    transition_length_bars: Optional[int] = Field(
        default=None,
        description="Transition length in bars (4/8/16/32/64) for display; crossfade_sec is source of truth.",
    )
    start_offset_bars: int = Field(
        default=0,
        ge=0,
        le=16,
        description="Bars to skip at start of Track B (intro); 0 = start at second 0.",
    )
    dj_comment: Optional[str] = Field(
        default=None,
        description="Professional DJ comment, e.g. 'Cattaneo mode: Iniciando transición progresiva de 64 barras…'",
    )
    fx_chain: Optional[str] = Field(
        default=None,
        description="Opus-Quad style: filters the DJ would use (e.g. 'High Pass Filter 30% on Track A during fade'). Not rendered yet.",
    )
    bass_swap_point: Optional[float] = Field(
        default=None,
        ge=0,
        description="Second within the transition when Track A loses bass and Track B gains it; used for highpass fade on B.",
    )
    bass_swap_sec: Optional[float] = Field(
        default=None,
        ge=0,
        description="Exact second where bass crosses (same as bass_swap_point).",
    )
    filter_type: Optional[str] = Field(
        default="high-pass fade",
        description="EQ filter type during transition, e.g. 'high-pass fade'.",
    )
    harmonic_distance: Optional[int] = Field(
        default=None,
        description="Camelot distance 0=same, 1=adjacent, 2+=distant.",
    )
    transition_style: Optional[str] = Field(
        default=None,
        description="long_atmospheric | short_rhythmic | wash_out.",
    )
    # Overlays IA: paths a samples (instrumentos/vocales) para amix; se resuelven en decision.
    overlay_paths: Optional[List[Path]] = Field(
        default=None,
        description="Optional overlay sample paths (instruments/vocals) to mix on top of A+B.",
    )
    overlay_bpms: Optional[List[float]] = Field(
        default=None,
        description="BPM de cada overlay (mismo orden que overlay_paths) para atempo.",
    )
    overlay_entry_sec: Optional[float] = Field(
        default=None,
        ge=0,
        description="Segundo donde entran los overlays; debe coincidir con phrase_starts_sec (inicio de frase 32 compases).",
    )
    overlay_instrument: Optional[str] = Field(
        default=None,
        description="Nombre de archivo del sample de instrumento (en assets/samples/instruments) para amix.",
    )
    overlay_vocal: Optional[str] = Field(
        default=None,
        description="Nombre de archivo del sample vocal (en assets/samples/vocals) para amix.",
    )
    overlay_instrument_url: Optional[str] = Field(
        default=None,
        description="URL del sample de instrumento (cloud); se descarga a temp antes de FFmpeg.",
    )
    overlay_vocal_url: Optional[str] = Field(
        default=None,
        description="URL del sample vocal (cloud); se descarga a temp antes de FFmpeg.",
    )
    overlay_instrument_bpm: Optional[float] = Field(
        default=None,
        ge=0,
        description="BPM del overlay instrument (cloud) para atempo.",
    )
    overlay_vocal_bpm: Optional[float] = Field(
        default=None,
        ge=0,
        description="BPM del overlay vocal (cloud) para atempo.",
    )
