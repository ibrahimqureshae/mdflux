"""
Audio transcription worker subprocess — spawned once per transcription request.

Reads one JSON params line from stdin:
  { "path": "...", "model_size": "base" }

Writes JSON lines to stdout:
  progress: {"type":"progress","stage":"<str>","frac":<float|null>,"heartbeat":<ts>}
  result:   {"type":"result","ok":<bool>,...}

The faster-whisper model downloads its weights on first use (~74 MB for "base").
That download happens inside WhisperModel() construction and is surfaced as a
"loading-model" progress event so the UI shows activity rather than freezing.
"""
import json
import os
import sys
import threading
import time


def _write(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _progress(stage: str, frac: float | None = None) -> None:
    _write({
        "type": "progress",
        "stage": stage,
        "frac": frac,
        "heartbeat": int(time.time()),
    })


def main() -> None:
    raw = sys.stdin.readline()
    try:
        params = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        _write({"type": "result", "ok": False, "error": {
            "code": "INTERNAL_ERROR",
            "title": "Audio worker received bad params",
            "detail": "Could not parse params.",
            "suggested_action": "Restart the app.",
        }})
        return

    path: str = params.get("path", "")
    model_size: str = params.get("model_size", "base")
    cpu_threads: int = int(params.get("cpu_threads", 0) or 0)  # 0 = use all cores

    # Signal that we're about to load the model (may download on first run).
    _progress("loading-model", 0.0)

    result_holder: dict = {}

    def progress_cb(frac, stage):
        _progress(stage, frac)

    def run() -> None:
        try:
            import audio as _audio
            text = _audio.transcribe(path, model_size=model_size,
                                     cpu_threads=cpu_threads, progress_cb=progress_cb)
            result_holder["markdown"] = text or ""
        except Exception as exc:  # noqa: BLE001
            result_holder["error"] = str(exc)

    t = threading.Thread(target=run, daemon=True)
    t.start()

    while t.is_alive():
        t.join(timeout=10.0)
        if t.is_alive():
            # Keep the sidecar's idle timeout alive; the actual progress tracking
            # happens inside the run() thread via progress_cb.
            _progress("transcribing")

    if "error" in result_holder:
        _write({"type": "result", "ok": False, "error": {
            "code": "CONVERSION_FAILED",
            "title": "Transcription failed",
            "detail": result_holder["error"],
            "suggested_action": (
                "The file may be in an unsupported format. "
                "Try WAV or MP3, or check that the file is not corrupted."
            ),
        }})
    else:
        md = result_holder.get("markdown", "")
        _write({"type": "result", "ok": True, "result": {
            "markdown": md,
            "meta": {
                "detected_format": "audio",
                "converter_path": "audio.faster_whisper",
                "warnings": [] if md.strip() else ["Transcription produced no text."],
            },
        }})


if __name__ == "__main__":
    main()
