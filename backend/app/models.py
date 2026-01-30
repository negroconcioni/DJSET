"""Pydantic models for API and LLM decision schema."""
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class SongAnalysis(BaseModel):
    """Result of musical analysis for one song."""

    bpm: float = Field(..., description="Beats per minute")
    key: str = Field(..., description="Musical key e.g. C major")
    key_scale: str = Field(default="major", description="major or minor")
    beats: list[float] = Field(default_factory=list, description="Beat times in seconds")
    energy: float = Field(..., ge=0, le=1, description="Overall energy 0-1")
    duration_sec: float = Field(..., description="Duration in seconds")
    path: Optional[Path] = None


class MixStrategy(BaseModel):
    """LLM output: strategy for the mix (JSON only)."""

    transition_type: str = Field(
        ...,
        description="One of: crossfade, beat_match_crossfade, drop_swap",
    )
    crossfade_sec: float = Field(
        ...,
        ge=0.5,
        le=32.0,
        description="Crossfade duration in seconds",
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
    reasoning: str = Field(default="", description="Short explanation for the strategy")
    transition_length_bars: Optional[int] = Field(
        default=None,
        description="Transition length in bars (4/8/16/32) for display; crossfade_sec is source of truth.",
    )
