"""Compatibility shim for the local Whisper model package.

Project code imports `whisper_local_transcriber as whisper`; this module
provides a `load_model(name, device=...)` wrapper delegating to
`whisper.load_model(...)` from the `openai-whisper` package (local model).

This file lets the existing code use the standard `whisper` distribution
without changing many import sites.
"""
from __future__ import annotations

try:
    import whisper as _whisper
except Exception as e:
    raise


def load_model(name: str, device: str = "cpu"):
    """Load and return a Whisper model instance.

    Args:
        name: model name (tiny, base, small, medium, large, large-v2, ...)
        device: device string accepted by openai-whisper ("cpu", "cuda", ...)
    """
    return _whisper.load_model(name, device=device)
