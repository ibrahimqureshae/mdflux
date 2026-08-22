from __future__ import annotations

import json
import os
import queue
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from .layout import bundled_python_path
from .models import CONVERSION_FIXTURES, FULL_IMPORT_MODULES, CheckResult
from .paths import app_data_root


def _run_python(
    python: Path,
    code: str,
    *,
    cwd: Path | None = None,
    timeout: float = 120.0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(python), "-I", "-c", code],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def verify_bundled_python_version(
    root: Path,
    *,
    platform: str,
    manifest: dict,
) -> CheckResult:
    python = bundled_python_path(root, platform)
    if not python.is_file():
        return CheckResult(
            "bundled-python-version",
            False,
            f"Missing bundled interpreter: {python}",
        )
    expected = manifest.get("python_version")
    proc = _run_python(
        python,
        "import platform; print(platform.python_version())",
    )
    if proc.returncode != 0:
        return CheckResult(
            "bundled-python-version",
            False,
            proc.stderr.strip() or proc.stdout.strip() or "Interpreter failed",
        )
    actual = proc.stdout.strip()
    if actual != expected:
        return CheckResult(
            "bundled-python-version",
            False,
            f"Expected {expected}, got {actual}",
        )
    return CheckResult("bundled-python-version", True, actual)


def verify_full_imports(root: Path, *, platform: str) -> CheckResult:
    python = bundled_python_path(root, platform)
    if not python.is_file():
        return CheckResult(
            "full-runtime-imports",
            False,
            f"Missing bundled interpreter: {python}",
        )
    modules = ", ".join(repr(name) for name in FULL_IMPORT_MODULES)
    code = (
        "import importlib; mods = ["
        + modules
        + "]; "
        + "[importlib.import_module(m) for m in mods]; "
        + "print('imports OK')"
    )
    proc = _run_python(python, code, timeout=180.0)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "Import failed"
        return CheckResult("full-runtime-imports", False, detail)
    return CheckResult("full-runtime-imports", True, "All required modules imported")


def _sidecar_request(
    python: Path,
    sidecar_dir: Path,
    request: dict,
    *,
    timeout: float = 60.0,
) -> tuple[dict | None, str]:
    payload = json.dumps(request) + "\n"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(sidecar_dir)
    # Windows pipe reads are not selectable. Drain stdout on a daemon thread
    # and pass each successive line through a queue so the caller can enforce
    # one deadline without leaving a non-daemon reader behind.
    process_group_options: dict[str, object] = {}
    if os.name == "nt":
        process_group_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        process_group_options["start_new_session"] = True
    proc = subprocess.Popen(
        [str(python), str(sidecar_dir / "main.py")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(sidecar_dir),
        env=env,
        **process_group_options,
    )
    stdout_thread: threading.Thread | None = None
    stderr_thread: threading.Thread | None = None

    def terminate_process_tree() -> None:
        if proc.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    try:
        if proc.stdin is None or proc.stdout is None or proc.stderr is None:
            return None, "Could not open sidecar subprocess streams"
        proc.stdin.write(payload)
        proc.stdin.flush()
        stdout_lines: queue.Queue[str | None] = queue.Queue()
        stderr_lines: list[str] = []

        def read_stdout() -> None:
            try:
                for output_line in proc.stdout:
                    stdout_lines.put(output_line)
            finally:
                stdout_lines.put(None)

        def read_stderr() -> None:
            stderr_lines.extend(proc.stderr.readlines())

        stdout_thread = threading.Thread(target=read_stdout, daemon=True)
        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(proc.args, timeout)
            try:
                line = stdout_lines.get(timeout=remaining)
            except queue.Empty:
                raise subprocess.TimeoutExpired(proc.args, timeout) from None
            if line is None:
                detail = "".join(stderr_lines).strip()
                return None, detail or "No matching IPC response on stdout"
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("id") == request.get("id") and (
                obj.get("ok") is not None or obj.get("error")
            ):
                return obj, ""
    except subprocess.TimeoutExpired:
        terminate_process_tree()
        raise
    finally:
        # Stop the tree while its root still exists. Closing stdin first lets the
        # sidecar exit and can orphan converter workers that retain the extracted
        # package directory on Windows.
        terminate_process_tree()
        if proc.stdin is not None and not proc.stdin.closed:
            proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            terminate_process_tree()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        if stdout_thread is not None:
            stdout_thread.join(timeout=1)
        if stderr_thread is not None:
            stderr_thread.join(timeout=1)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None and not stream.closed:
                stream.close()


def verify_sidecar_health(
    root: Path,
    *,
    platform: str,
    edition: str,
) -> CheckResult:
    sidecar_dir = root / "resources" / "sidecar"
    if edition == "full":
        python = bundled_python_path(root, platform)
    else:
        python = Path(sys.executable)

    request = {"v": 1, "id": "verify-health", "method": "health", "params": {}}
    try:
        response, error = _sidecar_request(python, sidecar_dir, request)
    except subprocess.TimeoutExpired:
        return CheckResult("sidecar-health", False, "Sidecar health request timed out")
    except OSError as exc:
        return CheckResult("sidecar-health", False, str(exc))

    if response is None:
        return CheckResult("sidecar-health", False, error)
    if not response.get("ok"):
        err = response.get("error") or {}
        detail = err.get("detail") or err.get("title") or "Sidecar health failed"
        return CheckResult("sidecar-health", False, str(detail))
    result = response.get("result") or {}
    version = result.get("markitdown_version") or "unknown"
    return CheckResult("sidecar-health", True, f"markitdown={version}")


def verify_conversions(
    root: Path,
    *,
    platform: str,
    edition: str,
    fixtures_dir: Path,
) -> list[CheckResult]:
    sidecar_dir = root / "resources" / "sidecar"
    if edition == "full":
        python = bundled_python_path(root, platform)
    else:
        python = Path(sys.executable)

    results: list[CheckResult] = []
    # Converters are third-party code and some parsers normalize or repair
    # container formats in place. Give each request an isolated copy.
    with tempfile.TemporaryDirectory(prefix="mdflux-fixture-") as scratch:
        scratch_dir = Path(scratch)
        for filename, ext in CONVERSION_FIXTURES:
            sample = fixtures_dir / filename
            if not sample.is_file():
                results.append(CheckResult(
                    f"conversion-fixture-{filename}", False,
                    f"Missing verifier fixture: {sample}", severity="error",
                ))
                continue
            isolated_sample = scratch_dir / filename
            shutil.copy2(sample, isolated_sample)
            request = {
                "v": 1, "id": f"verify-convert-{filename}",
                "method": "convert-one",
                "params": {"path": str(isolated_sample.resolve())},
            }
            try:
                response, error = _sidecar_request(
                    python, sidecar_dir, request, timeout=180.0
                )
            except subprocess.TimeoutExpired:
                results.append(CheckResult(
                    f"conversion-{ext}", False, f"{filename}: timed out"
                ))
                continue
            except OSError as exc:
                results.append(CheckResult(
                    f"conversion-{ext}", False, f"{filename}: {exc}"
                ))
                continue
            if response is None:
                results.append(CheckResult(
                    f"conversion-{ext}", False, f"{filename}: {error}"
                ))
                continue
            if not response.get("ok"):
                err = response.get("error") or {}
                detail = err.get("detail") or err.get("title") or "Conversion failed"
                results.append(CheckResult(
                    f"conversion-{ext}", False, f"{filename}: {detail}"
                ))
                continue
            markdown = (response.get("result") or {}).get("markdown") or ""
            if not str(markdown).strip():
                results.append(CheckResult(
                    f"conversion-{ext}", False,
                    f"{filename}: empty markdown output"
                ))
            else:
                results.append(CheckResult(
                    f"conversion-{ext}", True,
                    f"{filename}: {len(str(markdown))} chars"
                ))
    return results


def _snapshot_provisioning_paths(platform: str) -> dict[str, float | None]:
    root = app_data_root(platform)
    tracked = {
        "app_data_root": root,
        "runtimes": root / "runtimes",
        "active_runtime": root / "active-runtime.json",
    }
    snapshot: dict[str, float | None] = {}
    for key, path in tracked.items():
        if key == "app_data_root":
            continue
        if path.exists():
            snapshot[str(path)] = path.stat().st_mtime
        else:
            snapshot[str(path)] = None
    return snapshot


def verify_no_full_provisioning(
    before: dict[str, float | None],
    *,
    platform: str,
) -> CheckResult:
    after = _snapshot_provisioning_paths(platform)
    created: list[str] = []
    for path, mtime in after.items():
        if path == str(app_data_root(platform)):
            continue
        previous = before.get(path)
        path_obj = Path(path)
        if previous is None and path_obj.exists():
            created.append(path)
        elif previous is not None and path_obj.exists() and path_obj.stat().st_mtime > previous:
            created.append(path)
    if created:
        return CheckResult(
            "full-no-provisioning",
            False,
            "Full verification wrote provisioning state: " + ", ".join(created),
        )
    return CheckResult(
        "full-no-provisioning",
        True,
        "No new Lite provisioning paths were written",
    )


def snapshot_provisioning(platform: str) -> dict[str, float | None]:
    return _snapshot_provisioning_paths(platform)
