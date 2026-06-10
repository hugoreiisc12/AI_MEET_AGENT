"""
audio_preprocessor.py — Condicionamento de áudio antes da transcrição.

Estágio 1 da pipeline de qualidade:
  - highpass=f=80     (remove ronco grave)
  - lowpass=f=8000    (remove chiado agudo)
  - afftdn=nf=-25     (denoise espectral)
  - loudnorm          (normalização EBU R128 — equaliza volumes)
  - 16kHz mono PCM    (formato nativo do Whisper)

get_ffmpeg() resolve o binário de forma multiplataforma com fallback.
"""

import subprocess
from pathlib import Path

from interface.transcriber import TranscriptionError


def get_ffmpeg() -> str:
    """Resolve o binário do ffmpeg de forma multiplataforma.

    Ordem:
      1. shutil.which('ffmpeg') — PATH do sistema
      2. imageio_ffmpeg — fallback via pip (estático, funciona nos 3 SOs)
    """
    import shutil
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        raise RuntimeError(
            "ffmpeg não encontrado. Instale via brew/apt/winget "
            "ou: pip install imageio-ffmpeg"
        )


def preprocess_audio(webm_path: Path, output_path: Path | None = None) -> Path:
    """Aplica a cadeia de filtros ffmpeg no áudio bruto.

    Args:
        webm_path: Caminho do arquivo .webm original.
        output_path: Onde salvar o .wav processado.
                     Se None, usa o mesmo diretório com extensão .clean.wav.

    Returns:
        Caminho do arquivo .wav processado.

    Raises:
        TranscriptionError: Se o ffmpeg falhar.
    """
    if output_path is None:
        output_path = webm_path.with_suffix(".clean.wav")

    ffmpeg = get_ffmpeg()
    filter_chain = (
        "highpass=f=80,"
        "lowpass=f=8000,"
        "afftdn=nf=-25,"
        "loudnorm=I=-16:TP=-1.5:LRA=11"
    )

    try:
        subprocess.run(
            [
                ffmpeg, "-y", "-i", str(webm_path),
                "-af", filter_chain,
                "-ar", "16000",
                "-ac", "1",
                "-c:a", "pcm_s16le",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            timeout=300,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors="replace") if e.stderr else ""
        raise TranscriptionError(
            f"Falha no pré-processamento de áudio: {stderr[:500]}"
        ) from e
    except FileNotFoundError as e:
        raise TranscriptionError(
            f"Binário ffmpeg não encontrado: {ffmpeg}"
        ) from e

    return output_path


def pick_device_and_compute() -> tuple[str, str]:
    """Detecta automaticamente o device e compute_type para faster-whisper.

    Returns:
        (device, compute_type) — ex: ("cuda", "float16") ou ("cpu", "int8")
    """
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"
