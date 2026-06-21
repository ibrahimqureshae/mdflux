"""
Audio transcription — faster-whisper (CTranslate2-based, no PyTorch dependency).

Model weights (~74 MB for base) download from HuggingFace on first use and are
cached in the platform's default model cache directory.
"""

import importlib.util

AUDIO_EXTENSIONS: frozenset[str] = frozenset({
    ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".mp4", ".webm", ".aac",
})
AUDIO_TIMEOUT_SECS: int = 600


def is_available() -> bool:
    """
    True when faster-whisper is installed.

    Uses find_spec rather than importing — the heavy CTranslate2 import only ever
    happens inside the audio worker subprocess, never in the main sidecar process
    (see the rationale in ocr.is_available).
    """
    return importlib.util.find_spec("faster_whisper") is not None


def transcribe(path: str, model_size: str = "base", cpu_threads: int = 0, progress_cb=None) -> str:
    """
    Transcribe an audio file to timestamped Markdown.

    progress_cb(frac_or_None, stage_str) called per segment.
    cpu_threads: CTranslate2 thread count (0 = all cores). Limited during batch runs
    so concurrent workers don't oversubscribe the CPU.
    Model weights are downloaded on first use — the download is implicit in
    WhisperModel() construction and may take a moment. We emit a loading-model
    progress event before construction starts so the UI shows activity.
    """
    from faster_whisper import WhisperModel

    if progress_cb:
        progress_cb(None, "loading-model")

    model = WhisperModel(model_size, device="cpu", compute_type="int8",
                         cpu_threads=int(cpu_threads or 0))

    if progress_cb:
        progress_cb(0.0, "transcribing")

    segments, info = model.transcribe(path, beam_size=5)
    duration = max(info.duration or 1.0, 1.0)

    lines: list[str] = []
    for seg in segments:
        if progress_cb:
            frac = min(seg.start / duration, 0.99)
            progress_cb(frac, "transcribing")
        start = _fmt_ts(seg.start)
        end = _fmt_ts(seg.end)
        lines.append(f"**[{start} → {end}]** {seg.text.strip()}")

    return "\n\n".join(lines)


def _fmt_ts(secs: float) -> str:
    m = int(secs // 60)
    s = secs - m * 60
    return f"{m:02d}:{s:05.2f}"
