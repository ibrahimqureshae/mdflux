"""
Sidecar entry point — asyncio NDJSON IPC v1.

Three concurrent concerns on the same event loop:
  1. Stdin reader   — reads requests from Rust via run_in_executor (non-blocking).
  2. Conversion tasks — one asyncio.Task per convert-one request; keyed by request id.
  3. Provider checks  — background tasks, separate from conversion.

IPC v1 protocol:
  Request:  {"v":1, "id":"<str>", "method":"<str>", "params":{}}
  Success:  {"v":1, "id":"<str>", "ok":true,  "result":<value>}
  Failure:  {"v":1, "id":"<str>", "ok":false, "error":{"code","title","detail","suggested_action"}}
  Progress: {"v":1, "id":"<conv-id>", "type":"progress", "stage":"<str>", "frac":<float|null>, "heartbeat":<int>}

Stage 4 change: concurrent convert-one is now supported. Each request gets its
own asyncio.Event for cancellation, keyed by request id. "cancel" with no id
cancels all; with an "id" param it cancels one specific conversion.
"""
import asyncio
import functools
import importlib
import json
import os
import sys
import time
from pathlib import Path

import capabilities as _caps
import cleanup as _cleanup_mod
import health
import preflight
import provider as _provider
from errors import (
    CANCELLED,
    FILE_NOT_FOUND,
    INTERNAL_ERROR,
    MISSING_EXTRA,
    TIMEOUT,
    UNSUPPORTED_FORMAT,
    err,
)

TIMEOUT_SECS: int = 120
# AI cleanup per-chunk timeout. Lowered from 600 to 120 so Cancel doesn't wait up
# to 10 minutes for an in-flight LLM chunk to finish. The overall deadline still
# extends on each chunk completion, so a multi-chunk document is fine.
CLEANUP_LLM_TIMEOUT_SECS: int = 120
OCR_TIMEOUT_SECS: int = 600
AUDIO_TIMEOUT_SECS: int = 600
# Online-only cloud files (OneDrive Files On-Demand) must be downloaded on first read;
# a large one on a slow link can take a while, so a cloud file gets the long budget.
CLOUD_TIMEOUT_SECS: int = 600
# The worker returns the whole conversion result as one NDJSON line. asyncio's
# StreamReader defaults to a 64 KiB line limit, which a large document blows past
# ("Separator is not found, and chunk exceed the limit"). Raise it generously —
# input is already capped at 100 MB by preflight, so extracted text stays bounded.
WORKER_STREAM_LIMIT: int = 256 * 1024 * 1024
_SIDECAR_DIR: Path = Path(__file__).parent


class Sidecar:
    def __init__(self) -> None:
        self._write_lock: asyncio.Lock = asyncio.Lock()
        # Per-conversion cancel events keyed by request id.
        # Populated on convert-one, removed in _convert_safe's finally block.
        self._cancel_events: dict[str, asyncio.Event] = {}
        # Cap concurrent worker subprocesses so a 50-item batch doesn't spawn 50
        # MarkItDown/OCR/Whisper processes at once (multi-GB RAM, thrash). Defense-in-depth
        # even though Rust also serializes via its batch semaphore.
        cpu = os.cpu_count() or 4
        self._worker_sem = asyncio.Semaphore(max(2, min(8, cpu // 2)))
        # Track active worker subprocesses so we can kill them on shutdown (M11).
        self._active_procs: set[asyncio.subprocess.Process] = set()

    # ── Output ──────────────────────────────────────────────────────────────

    async def write(self, obj: dict) -> None:
        async with self._write_lock:
            sys.stdout.write(json.dumps(obj) + "\n")
            sys.stdout.flush()

    # ── Dispatch ────────────────────────────────────────────────────────────

    async def dispatch(self, req: dict) -> None:
        method = req.get("method") or req.get("cmd", "")
        req_id = req.get("id", "")
        params = req.get("params") or {}

        if method == "health":
            # Run in executor so importing 7 format modules doesn't block the event
            # loop (matters if health is called while conversions are in flight).
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, health.check)
            await self.write({"v": 1, "id": req_id, "ok": True, "result": result})

        elif method == "capabilities":
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, _caps.report)
            await self.write({"v": 1, "id": req_id, "ok": True, "result": result})

        elif method == "check-provider":
            asyncio.create_task(self._check_provider_safe(req_id, params))

        elif method == "convert-one":
            # Concurrent conversions are supported — no BUSY check.
            cancel_event = asyncio.Event()
            self._cancel_events[req_id] = cancel_event
            asyncio.create_task(self._convert_safe(req_id, params, cancel_event))

        elif method == "cleanup":
            # Deterministic + optional LLM cleanup. Cancellable via the same
            # per-id event dict so batch cancel (cancel-all) stops the LLM pass.
            cancel_event = asyncio.Event()
            self._cancel_events[req_id] = cancel_event
            asyncio.create_task(self._cleanup_safe(req_id, params, cancel_event))

        elif method == "cancel":
            target_id = params.get("id")
            cancelled_ids: list[str] = []
            if target_id:
                # Cancel one specific conversion.
                if target_id in self._cancel_events:
                    self._cancel_events[target_id].set()
                    cancelled_ids.append(target_id)
            else:
                # No id → cancel all active conversions (backwards-compat +
                # batch cancel path).
                for eid, event in self._cancel_events.items():
                    event.set()
                    cancelled_ids.append(eid)
            # Ack so the caller doesn't hang waiting for a response.
            await self.write({"v": 1, "id": req_id, "ok": True, "result": {"cancelled": cancelled_ids}})

        else:
            await self.write({"v": 1, "id": req_id, **err(
                "UNKNOWN_METHOD",
                "Unknown method",
                f"Unrecognised method: {method!r}",
                "Update the app.",
            )})

    # ── Conversion ──────────────────────────────────────────────────────────

    async def _convert_safe(
        self, conv_id: str, params: dict, cancel_event: asyncio.Event
    ) -> None:
        try:
            await self._convert(conv_id, params, cancel_event)
        except Exception as exc:  # noqa: BLE001
            await self.write({"v": 1, "id": conv_id, **err(
                INTERNAL_ERROR,
                "Internal error",
                str(exc),
                "Restart the app. If this keeps happening, re-install.",
            )})
        finally:
            self._cancel_events.pop(conv_id, None)

    async def _convert(
        self, conv_id: str, params: dict, cancel_event: asyncio.Event
    ) -> None:
        path: str = params.get("path", "")
        llm_cfg: dict | None = params.get("llm")

        if not path:
            await self.write({"v": 1, "id": conv_id, **err(
                FILE_NOT_FOUND, "No file path provided",
                "The request did not include a file path.",
                "Select a file and try again.",
            )})
            return

        if not os.path.exists(path):
            await self.write({"v": 1, "id": conv_id, **err(
                FILE_NOT_FOUND, "File not found",
                f"'{os.path.basename(path)}' does not exist at the given path.",
                "Check that the file hasn't been moved or deleted, then try again.",
            )})
            return

        ext = os.path.splitext(path)[1].lower()
        fmt_entry = _caps.ext_to_format(ext)

        if fmt_entry is None:
            await self.write({"v": 1, "id": conv_id, **err(
                UNSUPPORTED_FORMAT, "Format not supported",
                f"'{ext or '(no extension)'}' files can't be converted.",
                f"Use {_caps.SUPPORTED_LIST}.",
            )})
            return

        mode = fmt_entry.get("mode", "markitdown")

        # Online-only cloud file (OneDrive): reading it downloads it first, which counts
        # against the time budget. Acknowledge it in the UI; the standard path also gets a
        # longer timeout below (OCR/audio already have the long budget).
        cloud = preflight._is_cloud_placeholder(path)
        if cloud:
            await self._emit_progress(conv_id, "downloading")

        # ── OCR routing ────────────────────────────────────────────────────────
        if mode == "ocr":
            import ocr as _ocr
            if not _ocr.is_available():
                await self.write({"v": 1, "id": conv_id,
                                  **_missing_engine_err("ocr", fmt_entry["key"])})
                return
            await self._convert_ocr(conv_id, path, fmt_entry, cancel_event)
            return

        # ── Audio routing ──────────────────────────────────────────────────────
        if mode == "audio":
            import audio as _audio
            if not _audio.is_available():
                await self.write({"v": 1, "id": conv_id,
                                  **_missing_engine_err("audio", fmt_entry["key"])})
                return
            await self._convert_audio(conv_id, path, params, cancel_event)
            return

        # ── Standard MarkItDown routing ────────────────────────────────────────
        fmt = fmt_entry["key"]
        required_module = fmt_entry.get("module")
        converter_path = fmt_entry.get("converter", "")

        if cancel_event.is_set():
            await self.write({"v": 1, "id": conv_id, **_cancelled_err()})
            return

        await self._emit_progress(conv_id, "preflight")

        flight_err = preflight.check(path, ext)
        if flight_err:
            await self.write({"v": 1, "id": conv_id, **flight_err})
            return

        # Special case: PDF that appears to be scanned — route to OCR if available.
        # The detection parses the PDF with pdfminer, which is a multi-second
        # blocking call — run it in an executor so the event loop stays responsive
        # to cancel requests and other concurrent conversions. Race it against the
        # cancel event so Cancel is honoured immediately, not after the parse ends.
        if ext == ".pdf" and required_module:
            import ocr as _ocr
            if _ocr.is_available():
                loop = asyncio.get_running_loop()
                detect = asyncio.ensure_future(
                    loop.run_in_executor(None, _ocr.is_scanned_pdf, path)
                )
                cancel_wait = asyncio.ensure_future(cancel_event.wait())
                await asyncio.wait(
                    {detect, cancel_wait}, return_when=asyncio.FIRST_COMPLETED
                )
                cancel_wait.cancel()
                if cancel_event.is_set():
                    # The detached executor finishes pdfminer in the background; we
                    # don't wait on it — the user already asked to stop.
                    await self.write({"v": 1, "id": conv_id, **_cancelled_err()})
                    return
                if detect.result():
                    scanned_entry = {"key": "pdf-ocr", "converter": "ocr.RapidOCR"}
                    await self._convert_ocr(conv_id, path, scanned_entry, cancel_event, is_pdf=True)
                    return

        if required_module:
            try:
                importlib.import_module(required_module)
            except ImportError:
                e = err(
                    MISSING_EXTRA, "Required package missing",
                    f"The '{required_module}' package is not installed.",
                    "Open Diagnostics and click Repair to reinstall packages.",
                )
                e["error"]["diagnostics_key"] = fmt
                await self.write({"v": 1, "id": conv_id, **e})
                return

        worker_params: dict = {"path": path, "fmt": fmt, "converter_path": converter_path}
        if llm_cfg and llm_cfg.get("mode", "off") != "off":
            worker_params["llm"] = llm_cfg

        await self._run_worker_subprocess(
            conv_id=conv_id,
            worker_path=_SIDECAR_DIR / "worker.py",
            worker_params=worker_params,
            cancel_event=cancel_event,
            timeout_secs=CLOUD_TIMEOUT_SECS if cloud else TIMEOUT_SECS,
            timeout_msg=(
                "The file may still be downloading from the cloud. Make it available "
                "offline (right-click → Always keep on this device), then try again."
                if cloud else
                f"The conversion took longer than {TIMEOUT_SECS} seconds and was stopped."
            ),
        )

    # ── OCR conversion ──────────────────────────────────────────────────────────

    async def _convert_ocr(
        self,
        conv_id: str,
        path: str,
        fmt_entry: dict,
        cancel_event: asyncio.Event,
        is_pdf: bool = False,
    ) -> None:
        """Spawn ocr_worker.py for image files and scanned PDFs."""
        fmt = fmt_entry["key"]
        converter_path = fmt_entry.get("converter", "ocr.RapidOCR")
        worker_path = _SIDECAR_DIR / "ocr_worker.py"

        await self._run_worker_subprocess(
            conv_id=conv_id,
            worker_path=worker_path,
            worker_params={"path": path, "fmt": fmt, "is_pdf": is_pdf, "converter_path": converter_path},
            cancel_event=cancel_event,
            timeout_secs=OCR_TIMEOUT_SECS,
            timeout_msg=f"OCR took longer than {OCR_TIMEOUT_SECS} seconds and was stopped.",
        )

    # ── Audio transcription ────────────────────────────────────────────────────

    async def _convert_audio(
        self,
        conv_id: str,
        path: str,
        params: dict,
        cancel_event: asyncio.Event,
    ) -> None:
        """Spawn audio_worker.py for audio files."""
        model_size = params.get("audio_model", "base")
        worker_path = _SIDECAR_DIR / "audio_worker.py"

        await self._run_worker_subprocess(
            conv_id=conv_id,
            worker_path=worker_path,
            worker_params={"path": path, "model_size": model_size},
            cancel_event=cancel_event,
            timeout_secs=AUDIO_TIMEOUT_SECS,
            timeout_msg=f"Transcription took longer than {AUDIO_TIMEOUT_SECS} seconds and was stopped.",
        )

    # ── Generic worker subprocess runner ──────────────────────────────────────

    async def _run_worker_subprocess(
        self,
        conv_id: str,
        worker_path: Path,
        worker_params: dict,
        cancel_event: asyncio.Event,
        timeout_secs: int,
        timeout_msg: str,
    ) -> None:
        """
        Spawn a worker script as a subprocess, stream its progress/heartbeat events,
        and write the final result or error to the IPC channel.
        Cancellable; emits heartbeats every 5 s to keep Rust's idle timeout alive.
        """
        if cancel_event.is_set():
            await self.write({"v": 1, "id": conv_id, **_cancelled_err()})
            return

        # CPU-thread budget. Batch items (conv_id "batch-…") get a limited thread count
        # so N concurrent heavy workers (OCR/audio) don't oversubscribe the machine;
        # single-file conversions use all cores. The budget is set by Rust per machine.
        is_batch = conv_id.startswith("batch-")
        cpu_threads = 0
        sub_env = os.environ
        if is_batch:
            try:
                cpu_threads = int(os.environ.get("MDFLUX_BATCH_THREADS", "0") or "0")
            except ValueError:
                cpu_threads = 0
            if cpu_threads > 0:
                sub_env = {**os.environ}
                for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                           "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
                    sub_env[_v] = str(cpu_threads)
        params = {**worker_params, "cpu_threads": cpu_threads}

        # Windows: CREATE_NO_WINDOW (0x08000000) so the worker (a console app) never
        # flashes a command window. 0 elsewhere (ignored on POSIX).
        no_window = 0x0800_0000 if sys.platform == "win32" else 0

        # Acquire the semaphore so concurrent worker subprocesses are capped —
        # without this a 50-item batch spawns 50 heavy processes (OOM risk).
        async with self._worker_sem:
            if cancel_event.is_set():
                await self.write({"v": 1, "id": conv_id, **_cancelled_err()})
                return

            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    str(worker_path),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    limit=WORKER_STREAM_LIMIT,
                    env=sub_env,
                    creationflags=no_window,
                )
            except Exception as exc:  # noqa: BLE001
                await self.write({"v": 1, "id": conv_id, **err(
                    INTERNAL_ERROR, "Could not start worker process",
                    str(exc), "Restart the app.",
                )})
                return

            self._active_procs.add(proc)
            try:
                proc.stdin.write((json.dumps(params) + "\n").encode())
                await proc.stdin.drain()
                proc.stdin.close()

                final_msg: dict | None = None
                loop = asyncio.get_running_loop()
                deadline = loop.time() + timeout_secs
                last_hb = loop.time()

                try:
                    while True:
                        remaining = deadline - loop.time()
                        if remaining <= 0:
                            raise asyncio.TimeoutError()

                        if cancel_event.is_set():
                            await _kill(proc)
                            await self.write({"v": 1, "id": conv_id, **_cancelled_err()})
                            return

                        # Emit a heartbeat every 5 s to keep the Rust idle timeout alive.
                        if loop.time() - last_hb >= 5.0:
                            await self._emit_progress(conv_id, "processing")
                            last_hb = loop.time()

                        try:
                            raw = await asyncio.wait_for(
                                proc.stdout.readline(),
                                timeout=min(1.0, remaining),
                            )
                        except asyncio.TimeoutError:
                            if loop.time() >= deadline:
                                raise asyncio.TimeoutError()
                            continue

                        if not raw:
                            break

                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            continue

                        if msg.get("type") == "progress":
                            last_hb = loop.time()
                            await self._emit_progress(
                                conv_id,
                                msg.get("stage", "processing"),
                                msg.get("frac"),
                                msg.get("heartbeat"),
                            )
                        elif msg.get("type") == "result":
                            final_msg = msg
                            break

                except asyncio.TimeoutError:
                    await _kill(proc)
                    await self.write({"v": 1, "id": conv_id, **err(
                        TIMEOUT, "Timed out", timeout_msg,
                        "Try a smaller file, or split it into sections.",
                    )})
                    return

                if cancel_event.is_set():
                    await self.write({"v": 1, "id": conv_id, **_cancelled_err()})
                    return

                if final_msg is None:
                    await self.write({"v": 1, "id": conv_id, **err(
                        INTERNAL_ERROR,
                        "Worker stopped unexpectedly",
                        "The worker exited without producing a result.",
                        "Try the file again. If this keeps happening, restart the app.",
                    )})
                else:
                    response: dict = {"v": 1, "id": conv_id, "ok": final_msg.get("ok", False)}
                    if "result" in final_msg:
                        response["result"] = final_msg["result"]
                    if "error" in final_msg:
                        response["error"] = final_msg["error"]
                    elif not response["ok"]:
                        # Malformed worker result: ok=false but no error envelope.
                        # Synthesize one so Rust doesn't NPE indexing error.code.
                        response["error"] = err(
                            INTERNAL_ERROR,
                            "Worker error",
                            "The worker returned an invalid response (no error detail).",
                            "Try the file again. If this keeps happening, restart the app.",
                        )["error"]
                    await self.write(response)
            finally:
                self._active_procs.discard(proc)

    # ── Cleanup (Stage 5) ────────────────────────────────────────────────────

    async def _cleanup_safe(
        self, req_id: str, params: dict, cancel_event: asyncio.Event
    ) -> None:
        try:
            await self._cleanup(req_id, params, cancel_event)
        except Exception as exc:  # noqa: BLE001
            await self.write({"v": 1, "id": req_id, **err(
                INTERNAL_ERROR, "Cleanup failed",
                str(exc), "Try again, or turn cleanup off to keep the raw result.",
            )})
        finally:
            self._cancel_events.pop(req_id, None)

    async def _cleanup(
        self, req_id: str, params: dict, cancel_event: asyncio.Event
    ) -> None:
        markdown: str = params.get("markdown", "")
        source_format: str = params.get("source_format", "")
        rules: dict = params.get("rules", {})
        method: str = params.get("method", "rules")
        provider_cfg: dict = params.get("provider", {})

        if method == "ai":
            # AI cleans the RAW extraction directly — no deterministic pass.
            await self._cleanup_ai(req_id, markdown, provider_cfg, cancel_event)
            return

        # Rule-based: deterministic only.
        cleaned, summary = _cleanup_mod.clean(markdown, source_format, rules)
        await self.write({"v": 1, "id": req_id, "ok": True, "result": {
            "markdown": cleaned,
            "summary": summary,
            "llm_applied": False,
            "llm_notice": None,
        }})

    async def _cleanup_ai(
        self, req_id: str, markdown: str, provider_cfg: dict, cancel_event: asyncio.Event
    ) -> None:
        cleaned = markdown          # fail-soft default: the raw text, never lost
        llm_applied = False
        llm_notice: str | None = None

        if cancel_event.is_set():
            await self.write({"v": 1, "id": req_id, **_cancelled_err()})
            return

        loop = asyncio.get_running_loop()
        # The cleanup runs CHUNKED (see cleanup.llm_clean). progress is a shared dict the
        # worker thread updates as each chunk finishes; should_cancel lets it stop early.
        progress = {"done": 0, "total": 0}
        work = asyncio.ensure_future(loop.run_in_executor(
            None,
            functools.partial(
                _cleanup_mod.llm_clean, markdown, provider_cfg, CLEANUP_LLM_TIMEOUT_SECS,
                progress_cb=lambda d, t: progress.update(done=d, total=t),
                should_cancel=cancel_event.is_set,
            ),
        ))
        # Liveness: allow up to CLEANUP_LLM_TIMEOUT_SECS PER CHUNK. The deadline is pushed
        # forward whenever a chunk completes, so a long multi-chunk document is fine, but a
        # genuinely stuck chunk still trips it.
        deadline = loop.time() + CLEANUP_LLM_TIMEOUT_SECS + 30
        last_done = 0

        try:
            # Poll the worker: check for cancel every 2 s (snappy Cancel button),
            # emit a heartbeat every ~5 s so Rust's idle timeout never trips.
            last_hb = loop.time()
            while True:
                if cancel_event.is_set():
                    work.cancel()
                    await self.write({"v": 1, "id": req_id, **_cancelled_err()})
                    return
                done, _ = await asyncio.wait({work}, timeout=2.0)
                if work in done:
                    break
                if progress["done"] != last_done:   # a chunk landed → extend the deadline
                    last_done = progress["done"]
                    deadline = loop.time() + CLEANUP_LLM_TIMEOUT_SECS + 30
                if loop.time() >= deadline:
                    work.cancel()
                    raise asyncio.TimeoutError()
                if loop.time() - last_hb >= 5.0:
                    frac = (progress["done"] / progress["total"]) if progress["total"] else None
                    await self._emit_progress(req_id, "ai-cleanup", frac)
                    last_hb = loop.time()

            if cancel_event.is_set():   # cancel raced with the final chunk completing
                await self.write({"v": 1, "id": req_id, **_cancelled_err()})
                return

            llm_text = work.result()
            if isinstance(llm_text, str) and llm_text.strip():
                # Always present the AI result — the user decides whether to keep it.
                # The guardrail is advisory: it may attach a warning, never discards.
                cleaned = llm_text
                llm_applied = True
                llm_notice = _cleanup_mod.data_loss_warning(markdown, llm_text)
            elif not markdown.strip():
                pass  # empty input → empty output; no notice needed
            else:
                llm_notice = "AI cleanup returned nothing — kept the original text."
        except _cleanup_mod.CleanupCancelled:
            await self.write({"v": 1, "id": req_id, **_cancelled_err()})
            return
        except asyncio.TimeoutError:
            llm_notice = "AI cleanup timed out — kept the original text."
        except Exception as exc:  # noqa: BLE001 — fail soft, never lose the result
            _key = provider_cfg.get("key", "")
            safe_exc = str(exc).replace(_key, "[key]") if _key else str(exc)
            llm_notice = f"AI cleanup unavailable: {safe_exc} — kept the original text."

        summary = {
            "rules": [],
            "char_delta": len(cleaned) - len(markdown),
            "line_delta": (cleaned.count("\n") + 1) - (markdown.count("\n") + 1),
        }
        await self.write({"v": 1, "id": req_id, "ok": True, "result": {
            "markdown": cleaned,
            "summary": summary,
            "llm_applied": llm_applied,
            "llm_notice": llm_notice,
        }})

    async def _emit_progress(
        self,
        conv_id: str,
        stage: str,
        frac: float | None = None,
        heartbeat: int | None = None,
    ) -> None:
        await self.write({
            "v": 1,
            "id": conv_id,
            "type": "progress",
            "stage": stage,
            "frac": frac,
            "heartbeat": heartbeat or int(time.time()),
        })

    # ── Provider health check ────────────────────────────────────────────────

    async def _check_provider_safe(self, req_id: str, params: dict) -> None:
        try:
            await self._check_provider(req_id, params)
        except Exception as exc:  # noqa: BLE001
            await self.write({"v": 1, "id": req_id, "ok": True, "result": {
                "reachable": False,
                "detail": f"Check failed: {exc}",
                "usable": False,
            }})

    async def _check_provider(self, req_id: str, params: dict) -> None:
        ptype = params.get("provider", "local")
        base_url = params.get("base_url", "http://localhost:11434")
        key = params.get("key", "")
        loop = asyncio.get_running_loop()

        if ptype == "local":
            result = await loop.run_in_executor(None, _provider.check_local, base_url)
        elif ptype == "api_openai_compat":
            result = await loop.run_in_executor(None, _provider.check_openai_compat, base_url, key)
        elif ptype == "api_anthropic":
            result = await loop.run_in_executor(None, _provider.check_anthropic, key)
        else:
            result = {
                "reachable": False,
                "detail": f"Unknown provider type: {ptype!r}",
                "usable": False,
            }

        await self.write({"v": 1, "id": req_id, "ok": True, "result": result})


# ── Helpers ──────────────────────────────────────────────────────────────────

def _cancelled_err() -> dict:
    return err(CANCELLED, "Conversion cancelled", "The conversion was stopped by the user.", "")


def _missing_engine_err(engine: str, diag_key: str) -> dict:
    """Optional engine (OCR/audio) needed but not installed — point at the installer."""
    if engine == "ocr":
        title = "OCR engine not installed"
        detail = ("This image needs the OCR engine (RapidOCR), which isn't installed yet. "
                  "Scanned PDFs and image files require it.")
    else:
        title = "Audio engine not installed"
        detail = ("This audio file needs the transcription engine (faster-whisper), "
                  "which isn't installed yet.")
    e = err(MISSING_EXTRA, title, detail,
            "Open Diagnostics → Optional capabilities and click Install.")
    e["error"]["diagnostics_key"] = diag_key
    return e


async def _kill(proc: asyncio.subprocess.Process) -> None:
    try:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
    except ProcessLookupError:
        pass


# ── Entry ─────────────────────────────────────────────────────────────────────

async def async_main() -> None:
    sidecar = Sidecar()
    loop = asyncio.get_running_loop()

    try:
        while True:
            try:
                raw = await loop.run_in_executor(None, sys.stdin.readline)
            except Exception:
                break

            if not raw:
                break

            raw = raw.strip()
            if not raw:
                continue

            try:
                req = json.loads(raw)
            except json.JSONDecodeError as exc:
                await sidecar.write({"v": 1, "id": "", "ok": False, "error": {
                    "code": "INVALID_JSON",
                    "title": "Invalid request",
                    "detail": f"Could not parse request: {exc}",
                    "suggested_action": "Re-install the app.",
                }})
                continue

            # Guard against parseable-but-not-an-object JSON (e.g. "123", null, [],
            # true) — these have no .get method and would crash the sidecar.
            if not isinstance(req, dict):
                await sidecar.write({"v": 1, "id": "", "ok": False, "error": {
                    "code": "INVALID_JSON",
                    "title": "Invalid request",
                    "detail": "Request must be a JSON object.",
                    "suggested_action": "Re-install the app.",
                }})
                continue

            # Validate protocol version — a future v2 client must not be silently
            # misinterpreted as v1.
            req_v = req.get("v")
            if req_v != 1:
                req_id = req.get("id", "")
                await sidecar.write({"v": 1, "id": req_id, "ok": False, "error": {
                    "code": "BAD_VERSION",
                    "title": "Unsupported protocol version",
                    "detail": f"Expected v:1, got v:{req_v!r}.",
                    "suggested_action": "Update the app.",
                }})
                continue

            req_id = req.get("id", "")
            try:
                await sidecar.dispatch(req)
            except Exception as exc:  # noqa: BLE001
                await sidecar.write({"v": 1, "id": req_id, **err(
                    INTERNAL_ERROR, "Internal error",
                    str(exc), "Restart the app. If this keeps happening, re-install.",
                )})
    finally:
        # Kill any still-running worker subprocesses on shutdown so they don't
        # orphan and consume CPU/RAM for up to 600s after the app closes.
        for proc in list(sidecar._active_procs):
            await _kill(proc)
        sidecar._active_procs.clear()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
