"""Mezcla profesional: 4 inputs fijos (track_a, track_b, cloud_vocal, cloud_instrument). Crossfade + amix en cadena."""
import subprocess
from pathlib import Path
from typing import Union


def render_professional_mix(
    path_a: Union[str, Path],
    path_b: Union[str, Path],
    path_cloud_vocal: Union[str, Path],
    path_cloud_instrument: Union[str, Path],
    output_path: Union[str, Path],
    cross_d: float,
    *,
    apply_highpass_a: bool = False,
    overlay_entry_sec: float = 0.0,
    target_bpm: float = 0.0,
    vocal_bpm: float = 120.0,
    instrument_bpm: float = 120.0,
) -> Path:
    """
    Siempre 4 inputs: [0]=track_a, [1]=track_b, [2]=cloud_vocal, [3]=cloud_instrument.
    Filtro: [0:a][1:a]acrossfade -> [mixed_main]; [mixed_main][2:a]atempo,adelay -> [with_vocal]; [with_vocal][3:a]atempo,adelay -> [final_out]; loudnorm.
    adelay usa overlay_entry_sec (breakdown) en ms. atempo = target_bpm / overlay_bpm por sample.
    """
    path_a = Path(path_a)
    path_b = Path(path_b)
    path_cloud_vocal = Path(path_cloud_vocal)
    path_cloud_instrument = Path(path_cloud_instrument)
    output_path = Path(output_path)

    cross_d = round(float(cross_d), 3)
    cross_d = max(0.1, min(cross_d, 120.0))
    entry_sec = max(0.0, float(overlay_entry_sec))
    entry_ms = int(round(entry_sec * 1000))
    target_bpm = float(target_bpm or 0.0)
    vocal_bpm = float(vocal_bpm or 120.0)
    instrument_bpm = float(instrument_bpm or 120.0)

    # atempo por overlay (sync al BPM del set)
    ratio_v = target_bpm / vocal_bpm if (target_bpm > 0 and vocal_bpm > 0) else 1.0
    ratio_v = max(0.5, min(2.0, ratio_v))
    ratio_i = target_bpm / instrument_bpm if (target_bpm > 0 and instrument_bpm > 0) else 1.0
    ratio_i = max(0.5, min(2.0, ratio_i))

    across = f"acrossfade=d={cross_d}:curve1=hsin:curve2=hsin"
    if apply_highpass_a:
        base_chain = "[0:a]highpass=f=80[ahp];[ahp][1:a]" + across + "[mixed_main]"
    else:
        base_chain = "[0:a][1:a]" + across + "[mixed_main]"

    # [mixed_main][2:a]atempo,adelay -> [with_vocal]; [with_vocal][3:a]atempo,adelay -> [final_out]
    vocal_chain = f"[2:a]atempo={round(ratio_v, 4)},adelay={entry_ms}|{entry_ms}[vocal]"
    instrument_chain = f"[3:a]atempo={round(ratio_i, 4)},adelay={entry_ms}|{entry_ms}[instrument]"
    amix1 = "[mixed_main][vocal]amix=inputs=2:duration=first:dropout_transition=2[with_vocal]"
    amix2 = "[with_vocal][instrument]amix=inputs=2:duration=first:dropout_transition=2[final_out]"
    filter_with_loudnorm = ";".join([
        base_chain,
        vocal_chain,
        instrument_chain,
        amix1,
        amix2,
        "[final_out]loudnorm=I=-16[out]",
    ])
    filter_no_loudnorm = ";".join([
        base_chain,
        vocal_chain,
        instrument_chain,
        amix1,
        amix2,
        "[final_out]anull[out]",
    ])

    inputs = [path_a, path_b, path_cloud_vocal, path_cloud_instrument]
    command = [
        "ffmpeg", "-y",
        *[arg for p in inputs for arg in ("-i", str(p))],
        "-filter_complex", filter_with_loudnorm,
        "-map", "[out]",
        "-acodec", "pcm_s16le",
        str(output_path),
    ]

    # Debug: comando final FFmpeg
    print("[processor.py] FFmpeg command:", " ".join(command))

    result = subprocess.run(command, capture_output=True, text=True)

    if result.returncode != 0 and ("loudnorm" in (result.stderr or "") or "loudnorm" in (result.stdout or "")):
        command_fallback = [
            "ffmpeg", "-y",
            *[arg for p in inputs for arg in ("-i", str(p))],
            "-filter_complex", filter_no_loudnorm,
            "-map", "[out]",
            "-acodec", "pcm_s16le",
            str(output_path),
        ]
        print("[processor.py] FFmpeg fallback (no loudnorm):", " ".join(command_fallback))
        result = subprocess.run(command_fallback, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg Error (exit {result.returncode}): {result.stderr or result.stdout}")

    return output_path
