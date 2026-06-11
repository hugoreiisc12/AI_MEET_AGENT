"""
audio_preprocessor.py — Condicionamento de áudio antes da transcrição.

Estágio 1 da pipeline de transcrição comprovada:
  highpass=f=80, lowpass=f=8000, afftdn (denoise), loudnorm (EBU R128),
  reamostragem para 16kHz mono PCM.
"""
import subprocess
from pathlib import Path


def get_ffmpeg() -> str:
    path = __import__("shutil").which("ffmpeg")
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


def preprocess_audio(webm_path: Path) -> Path:
    wav_path = webm_path.with_suffix(".clean.wav")
    subprocess.run(
        [
            get_ffmpeg(), "-y", "-i", str(webm_path),
            "-af", (
                "highpass=f=80,"
                "lowpass=f=8000,"
                "afftdn=nf=-25,"
                "loudnorm=I=-16:TP=-1.5:LRA=11"
            ),
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
            str(wav_path),
        ],
        check=True, capture_output=True,
    )
    return wav_path
