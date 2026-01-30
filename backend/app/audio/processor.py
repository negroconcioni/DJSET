"""Mezcla profesional: Pioneer Opus Quad — curvas hsin, Sound Color FX, loudnorm. Sampler: amix + atempo (Sync total)."""
import subprocess
from pathlib import Path
from typing import List, Optional, Union


def render_professional_mix(
    path_a: Union[str, Path],
    path_b: Union[str, Path],
    output_path: Union[str, Path],
    cross_d: float,
    *,
    apply_highpass_a: bool = False,
    overlay_paths: Optional[List[Union[str, Path]]] = None,
    overlay_bpms: Optional[List[float]] = None,
    target_bpm: Optional[float] = None,
    overlay_entry_sec: Optional[float] = None,
) -> Path:
    """
    Combina los dos tracks principales con acrossfade; suma los overlays elegidos por la IA con amix.
    - Recibe los nombres/rutas de archivos elegidos (overlay_instrument, overlay_vocal) en overlay_paths.
    - FFmpeg: [0:a][1:a] acrossfade -> [ab]; luego [ab] + overlays con amix (suma a la mezcla de los dos tracks).
    - Sincronización total (emula Sync Opus Quad): filtro atempo en cada sample para estirar/encoger hasta
      coincidir con el BPM exacto del set (target_bpm / overlay_bpm). No se pegan samples sin procesar.
    - overlay_entry_sec: adelay para que la trompeta/vocal entren en inicio de frase (32 compases).
    - loudnorm al final (Loudness Pro).
    """
    path_a = Path(path_a)
    path_b = Path(path_b)
    output_path = Path(output_path)
    overlays = [Path(p) for p in (overlay_paths or []) if p]
    bpms = list(overlay_bpms or [])
    if len(bpms) != len(overlays):
        bpms = [0.0] * len(overlays)  # sin atempo si faltan BPM
    target_bpm = float(target_bpm or 0.0)
    entry_sec = max(0.0, float(overlay_entry_sec or 0.0))
    entry_ms = int(round(entry_sec * 1000))

    cross_d = round(float(cross_d), 3)
    cross_d = max(0.5, min(cross_d, 120.0))

    # Opus Quad: curvas sinusoidales hsin
    across = f"acrossfade=d={cross_d}:curve1=hsin:curve2=hsin"
    if apply_highpass_a:
        base_chain = "[0:a]highpass=f=80[ahp];[ahp][1:a]" + across + "[ab]"
    else:
        base_chain = "[0:a][1:a]" + across + "[ab]"

    if not overlays:
        filter_with_loudnorm = base_chain + ";[ab]loudnorm=I=-16[out]"
        filter_no_loudnorm = base_chain + ";[ab]anull[out]"
        inputs = [path_a, path_b]
    else:
        # Sampler: cada archivo elegido → atempo (Sync total al BPM del set) + adelay (fraseo)
        n_overlay = len(overlays)
        overlay_filters: List[str] = []
        for i in range(n_overlay):
            ratio = target_bpm / bpms[i] if (target_bpm > 0 and bpms[i] > 0) else 1.0
            ratio = max(0.5, min(2.0, ratio))  # atempo: estira/encoge al BPM exacto del set (Opus Quad Sync)
            overlay_filters.append(f"[{2 + i}:a]atempo={round(ratio, 4)},adelay={entry_ms}|{entry_ms}[o{i}]")
        amix_inputs = "[ab]" + "".join(f"[o{i}]" for i in range(n_overlay))
        amix_part = f"amix=inputs={1 + n_overlay}:duration=first:dropout_transition=2"
        filter_with_loudnorm = base_chain + ";" + ";".join(overlay_filters) + ";" + amix_inputs + amix_part + "[mixed];[mixed]loudnorm=I=-16[out]"
        filter_no_loudnorm = base_chain + ";" + ";".join(overlay_filters) + ";" + amix_inputs + amix_part + "[out]"
        inputs = [path_a, path_b] + overlays

    command = [
        "ffmpeg", "-y",
        *[arg for p in inputs for arg in ("-i", str(p))],
        "-filter_complex", filter_with_loudnorm,
        "-map", "[out]",
        "-acodec", "pcm_s16le",
        str(output_path),
    ]

    result = subprocess.run(command, capture_output=True, text=True)

    if result.returncode != 0 and (result.returncode == 234 or "loudnorm" in (result.stderr or "") or "loudnorm" in (result.stdout or "")):
        command_fallback = [
            "ffmpeg", "-y",
            *[arg for p in inputs for arg in ("-i", str(p))],
            "-filter_complex", filter_no_loudnorm,
            "-map", "[out]",
            "-acodec", "pcm_s16le",
            str(output_path),
        ]
        result = subprocess.run(command_fallback, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg Error (exit {result.returncode}): {result.stderr or result.stdout}")

    return output_path
