"""
Conversion worker subprocess — spawned once per convert-one request.

Reads one JSON params line from stdin.
Writes JSON lines to stdout:
  progress: {"type":"progress","stage":"<stage>","frac":<float|null>,"heartbeat":<unix_ts>}
  result:   {"type":"result","ok":<bool>,...}

Designed to be killed cleanly by SIGTERM / terminate() from the sidecar.
The MarkItDown call runs in a daemon thread so terminate() stops the process
immediately regardless of where the conversion is.
"""
import json
import os
import sys
import threading
import time


def _build_llm_client(cfg: dict | None):
    """Build an OpenAI-compatible client from the LLM config dict, or None."""
    if not cfg or cfg.get("mode", "off") == "off":
        return None
    try:
        import openai
        base_url = cfg.get("base_url", "")
        key = cfg.get("key", "") or "local"
        if cfg.get("api_type") == "anthropic":
            # Anthropic's API is not OpenAI-compatible (no /v1/chat/completions).
            # MarkItDown expects an openai.OpenAI client for image description, so
            # image description is not available with Anthropic in v1. Return None
            # so MarkItDown runs without LLM — the text result is never lost.
            return None
        # Local servers (Ollama) typically expose the OpenAI-compatible API under
        # /v1, but the user's configured base URL often omits it (e.g.
        # "http://localhost:11434"). The OpenAI SDK appends "/chat/completions"
        # to whatever base it's given, so ensure a /v1 suffix for local mode.
        # LM Studio and hosted APIs already include /v1, so don't double it.
        if cfg.get("mode") == "local" and base_url:
            b = base_url.rstrip("/")
            base_url = b if b.endswith("/v1") else b + "/v1"
        return openai.OpenAI(
            base_url=base_url or "http://localhost:11434/v1",
            api_key=key or "local",
        )
    except Exception:
        return None


def _llm_model(cfg: dict | None) -> str | None:
    if not cfg:
        return None
    return cfg.get("model") or None


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


def _friendly_conversion_error(exc: Exception) -> tuple[str, str]:
    """Return (detail, suggested_action) — readable, not raw exception names."""
    blob = f"{type(exc).__name__} {exc}".lower()
    if "password" in blob or "encrypted" in blob:
        return (
            "This file is password-protected.",
            "Unlock it, save an unprotected copy, then try again.",
        )
    if (
        "pdfsyntax" in blob
        or "no /root" in blob
        or "eof marker" in blob
        or "startxref" in blob
        or ("xref" in blob and "pdf" in blob)
    ):
        return (
            "This PDF is damaged or not a real PDF.",
            "Open it in a PDF reader to check, or export it again from the original app.",
        )
    if "badzipfile" in blob or "not a zip" in blob or "truncated zip" in blob:
        return (
            "This Office file is damaged or incomplete.",
            "Open it in Word, Excel, or PowerPoint, save a new copy, then try again.",
        )
    if "permission" in blob or "access is denied" in blob or "errno 13" in blob:
        return (
            "The file could not be read.",
            "Close it if it is open in another app, then try again.",
        )
    return (
        "The file could not be converted.",
        "The file may be corrupted or contain content that can't be extracted. Try another file.",
    )


def _present_markdown(fmt: str, text: str) -> str:
    """JSON/XML come through as raw text — wrap them so Preview renders as a code block."""
    text = text or ""
    if not text.strip():
        return text
    if fmt == "json":
        body = text.strip()
        if body.startswith("```"):
            return text
        try:
            body = json.dumps(json.loads(body), indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
        return f"```json\n{body.rstrip()}\n```\n"
    if fmt == "xml":
        body = text.strip()
        if body.startswith("```"):
            return text
        # HtmlConverter may already have turned XML into Markdown.
        if body.startswith("<"):
            return f"```xml\n{body}\n```\n"
        return text
    return text


def main() -> None:
    raw = sys.stdin.readline()
    try:
        params = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        _write({"type": "result", "ok": False, "error": {
            "code": "INTERNAL_ERROR",
            "title": "Worker received bad params",
            "detail": "Could not parse worker params.",
            "suggested_action": "Restart the app.",
        }})
        return

    path: str = params.get("path", "")
    fmt: str = params.get("fmt", "")
    converter_path: str = params.get("converter_path", "")

    _progress("extracting")

    llm_cfg: dict | None = params.get("llm")
    llm_client = _build_llm_client(llm_cfg) if llm_cfg else None

    result_holder: dict = {}

    def run() -> None:
        try:
            from markitdown import MarkItDown
            md = MarkItDown(llm_client=llm_client, llm_model=_llm_model(llm_cfg)) if llm_client else MarkItDown()
            try:
                r = md.convert(path)
            except UnicodeDecodeError:
                # MarkItDown guessed the wrong encoding (it samples the start of the
                # file). Retry forcing UTF-8 via convert_stream so non-ASCII content
                # (Arabic, accents, etc.) decodes correctly.
                from markitdown import StreamInfo
                ext = os.path.splitext(path)[1]
                md2 = MarkItDown(llm_client=llm_client, llm_model=_llm_model(llm_cfg)) if llm_client else MarkItDown()
                with open(path, "rb") as f:
                    r = md2.convert_stream(
                        f, stream_info=StreamInfo(extension=ext, charset="utf-8")
                    )
            result_holder["markdown"] = _present_markdown(fmt, r.text_content or "")
        except Exception as exc:  # noqa: BLE001
            if llm_client:
                # Fail soft: retry without LLM so the text result is never lost.
                # Scrub the API key from the exception string — some OpenAI-compat
                # servers echo request headers in error bodies. Only scrub when
                # the key is non-empty (local mode sends key=""; str.replace("",
                # "[key]") would insert [key] between every character).
                _key = llm_cfg.get("key", "")
                safe_exc = str(exc).replace(_key, "[key]") if _key else str(exc)
                try:
                    from markitdown import MarkItDown as _MD
                    r2 = _MD().convert(path)
                    result_holder["markdown"] = _present_markdown(fmt, r2.text_content or "")
                    result_holder["llm_notice"] = f"LLM image description unavailable: {safe_exc}"
                    return
                except Exception as exc2:  # noqa: BLE001
                    result_holder["error"] = exc2
                    result_holder["llm_notice"] = f"LLM image description unavailable: {safe_exc}"
            else:
                result_holder["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()

    # Join in 10 s slices; send heartbeats so sidecar knows we're alive.
    while t.is_alive():
        t.join(timeout=10.0)
        if t.is_alive():
            _progress("extracting")

    if "error" in result_holder:
        detail, action = _friendly_conversion_error(result_holder["error"])
        _write({"type": "result", "ok": False, "error": {
            "code": "CONVERSION_FAILED",
            "title": "Conversion failed",
            "detail": detail,
            "suggested_action": action,
        }})
    else:
        warnings: list[str] = []
        if notice := result_holder.get("llm_notice"):
            warnings.append(notice)
        if not result_holder["markdown"].strip():
            warnings.append("No text could be extracted from this file.")
        _write({"type": "result", "ok": True, "result": {
            "markdown": result_holder["markdown"],
            "meta": {
                "detected_format": fmt,
                "converter_path": converter_path,
                "warnings": warnings,
            },
        }})


if __name__ == "__main__":
    main()
