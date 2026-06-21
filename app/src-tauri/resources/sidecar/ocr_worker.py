"""
OCR worker subprocess — spawned once per OCR request.

Reads one JSON params line from stdin:
  { "path": "...", "fmt": "...", "is_pdf": bool }

Writes JSON lines to stdout:
  progress: {"type":"progress","stage":"<str>","frac":<float|null>,"heartbeat":<ts>}
  result:   {"type":"result","ok":<bool>,...}
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
            "title": "OCR worker received bad params",
            "detail": "Could not parse params.",
            "suggested_action": "Restart the app.",
        }})
        return

    path: str = params.get("path", "")
    fmt: str = params.get("fmt", "image")
    is_pdf: bool = params.get("is_pdf", False)
    cpu_threads: int = int(params.get("cpu_threads", 0) or 0)  # 0 = use all cores

    _progress("ocr-init")

    result_holder: dict = {}

    def run() -> None:
        try:
            import ocr as _ocr
            if is_pdf:
                last_hb = [time.time()]

                def progress_cb(frac, stage):
                    now = time.time()
                    if now - last_hb[0] >= 5.0:
                        _progress("ocr-page", frac)
                        last_hb[0] = now

                text = _ocr.ocr_pdf(path, progress_cb=progress_cb, intra_op_threads=cpu_threads)
            else:
                _progress("ocr-image")
                text = _ocr.ocr_image(path, intra_op_threads=cpu_threads)

            result_holder["markdown"] = text or ""
        except Exception as exc:  # noqa: BLE001
            result_holder["error"] = str(exc)

    t = threading.Thread(target=run, daemon=True)
    t.start()

    while t.is_alive():
        t.join(timeout=10.0)
        if t.is_alive():
            _progress("ocr-processing")

    if "error" in result_holder:
        _write({"type": "result", "ok": False, "error": {
            "code": "CONVERSION_FAILED",
            "title": "OCR failed",
            "detail": result_holder["error"],
            "suggested_action": (
                "The file may be too complex for OCR. "
                "Try a different image or simpler scan."
            ),
        }})
    else:
        md = result_holder.get("markdown", "")
        _write({"type": "result", "ok": True, "result": {
            "markdown": md,
            "meta": {
                "detected_format": fmt,
                "converter_path": "ocr.RapidOCR",
                "warnings": [] if md.strip() else ["OCR found no text in this file."],
            },
        }})


if __name__ == "__main__":
    main()
