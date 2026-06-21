"""
Single source of truth for format capabilities.

Both the diagnostics report and convert.py routing read from this module so the
panel and error messages can never disagree about what is available.
"""
import importlib
import importlib.util
import sys
import os
from pathlib import Path

SIDECAR_VERSION = "0.6.0"

# Core formats — provisioned at Stage 0 and always available.
# module: None means no extra needed beyond markitdown core.
_CORE_FORMATS: list[dict] = [
    {
        "key": "pdf",
        "label": "PDF",
        "extensions": [".pdf"],
        "module": "pdfminer",
        "converter": "markitdown.converters.pdf.PdfConverter",
        "mode": "markitdown",
    },
    {
        "key": "docx",
        "label": "Word (DOCX)",
        "extensions": [".docx"],
        "module": "mammoth",
        "converter": "markitdown.converters.docx.DocxConverter",
        "mode": "markitdown",
    },
    {
        "key": "pptx",
        "label": "PowerPoint (PPTX)",
        "extensions": [".pptx"],
        "module": "pptx",
        "converter": "markitdown.converters.pptx.PptxConverter",
        "mode": "markitdown",
    },
    {
        "key": "xlsx",
        "label": "Excel (XLSX)",
        "extensions": [".xlsx"],
        "module": "openpyxl",
        "converter": "markitdown.converters.xlsx.XlsxConverter",
        "mode": "markitdown",
    },
    {
        "key": "xls",
        "label": "Excel (XLS)",
        "extensions": [".xls"],
        "module": "xlrd",
        "converter": "markitdown.converters.xlsx.XlsxConverter",
        "mode": "markitdown",
    },
    {
        "key": "epub",
        "label": "EPUB",
        "extensions": [".epub"],
        # MarkItDown's EPUB converter uses only stdlib zipfile + defusedxml (PSF) + its
        # own HtmlConverter — NOT ebooklib (AGPL). Probe defusedxml so the health check
        # reflects the real dependency and the codebase stays copyleft-free.
        "module": "defusedxml",
        "converter": "markitdown.converters.epub.EpubConverter",
        "mode": "markitdown",
        "note": "Best-effort — complex layouts may not fully convert",
    },
    {
        "key": "html",
        "label": "HTML",
        "extensions": [".html", ".htm"],
        "module": "bs4",
        "converter": "markitdown.converters.html.HtmlConverter",
        "mode": "markitdown",
    },
    {
        "key": "csv",
        "label": "CSV",
        "extensions": [".csv"],
        "module": None,
        "converter": "markitdown.converters.csv.CsvConverter",
        "mode": "markitdown",
    },
    {
        "key": "json",
        "label": "JSON",
        "extensions": [".json"],
        "module": None,
        "converter": "markitdown.converters.plain_text.PlainTextConverter",
        "mode": "markitdown",
    },
    {
        "key": "xml",
        "label": "XML",
        "extensions": [".xml"],
        "module": None,
        "converter": "markitdown.converters.html.HtmlConverter",
        "mode": "markitdown",
    },
]

# OCR-based image formats — activated when RapidOCR is installed.
_OCR_FORMATS: list[dict] = [
    {
        "key": "image",
        "label": "Images (JPG, PNG, TIFF, WebP…)",
        "extensions": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".tiff", ".tif", ".bmp"],
        "module": "rapidocr_onnxruntime",
        "converter": "ocr.RapidOCR",
        "mode": "ocr",
        "note": None,
    },
]

# Audio formats — activated when faster-whisper is installed.
_AUDIO_FORMATS: list[dict] = [
    {
        "key": "audio",
        "label": "Audio (MP3, WAV, M4A, OGG, FLAC…)",
        "extensions": [".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"],
        "module": "faster_whisper",
        "converter": "audio.faster_whisper",
        "mode": "audio",
        "note": None,
    },
]


# ── Extension → format lookup (used by convert.py and main.py) ───────────────

def ext_to_format(ext: str) -> dict | None:
    """
    Return the format entry for a file extension, or None if the extension is not
    a recognised format at all.

    Note: this always recognises image/audio extensions even when the optional
    engine isn't installed — the routing layer (main.py) is responsible for
    emitting a MISSING_EXTRA error that points the user to the install button.
    Returning None here would mislabel a known format as "unsupported".
    """
    all_formats = _CORE_FORMATS + _OCR_FORMATS + _AUDIO_FORMATS
    for fmt in all_formats:
        if ext in fmt["extensions"]:
            return fmt
    return None


SUPPORTED_LIST = "PDF, DOCX, PPTX, XLSX, HTML, CSV, JSON, XML, EPUB, images, or audio"


# ── Diagnostics report ────────────────────────────────────────────────────────

def _probe(fmt: dict) -> dict:
    """Probe one format entry and return a capability row."""
    module = fmt["module"]
    status = "available"
    error_msg = None
    module_version = None

    if module is not None:
        try:
            mod = importlib.import_module(module)
            for attr in ("__version__", "VERSION", "version"):
                v = getattr(mod, attr, None)
                if v and isinstance(v, (str, int, float)):
                    module_version = str(v)
                    break
        except ImportError:
            status = "missing"
            error_msg = f"'{module}' is not installed."
        except Exception as exc:
            status = "broken"
            error_msg = str(exc)

    return {
        "key": fmt["key"],
        "label": fmt["label"],
        "extensions": fmt["extensions"],
        "module": module,
        "module_version": module_version,
        "converter": fmt.get("converter"),
        "status": status,
        "error": error_msg,
        "note": fmt.get("note"),
    }


# Module → distribution name, for version lookup without importing the module.
_DIST_NAMES = {
    "rapidocr_onnxruntime": "rapidocr-onnxruntime",
    "faster_whisper": "faster-whisper",
}


def _dist_version(module: str) -> str | None:
    """Get a package version via metadata without importing the (heavy) module."""
    import importlib.metadata as md
    try:
        return md.version(_DIST_NAMES.get(module, module))
    except Exception:
        return None


def _probe_optional(fmt: dict) -> dict:
    """
    Probe an optional-engine format (OCR/audio) WITHOUT importing the engine.

    Importing rapidocr_onnxruntime / faster_whisper loads native runtimes
    (onnxruntime, CTranslate2) into the main sidecar process, which stalls the
    asyncio Proactor event loop's subprocess pipe handling on Windows. We only
    check presence via find_spec and read the version from package metadata.
    """
    module = fmt["module"]
    installed = importlib.util.find_spec(module) is not None
    return {
        "key": fmt["key"],
        "label": fmt["label"],
        "extensions": fmt["extensions"],
        "module": module,
        "module_version": _dist_version(module) if installed else None,
        "converter": fmt.get("converter"),
        "status": "available" if installed else "missing",
        "error": None if installed else f"'{module}' is not installed.",
        "note": fmt.get("note"),
    }


def _ocr_optional_status() -> dict:
    """Return the optional.ocr block for the capabilities report (no heavy import)."""
    if importlib.util.find_spec("rapidocr_onnxruntime") is not None:
        return {
            "status": "installed",
            "engine": "rapidocr-onnxruntime",
            "size_hint": "~200 MB",
            "note": "RapidOCR — scanned PDFs and image files",
        }
    return {
        "status": "not_installed",
        "engine": "rapidocr-onnxruntime",
        "size_hint": "~200 MB (ONNX Runtime + model)",
        "note": "Install to convert scanned PDFs and image files",
    }


def _audio_optional_status() -> dict:
    """Return the optional.audio block for the capabilities report (no heavy import)."""
    if importlib.util.find_spec("faster_whisper") is not None:
        return {
            "status": "installed",
            "engine": "faster-whisper",
            "size_hint": "~100 MB + model weights on first use",
            "note": "Faster-Whisper — local audio transcription",
        }
    return {
        "status": "not_installed",
        "engine": "faster-whisper",
        "size_hint": "~100 MB (CTranslate2) + model weights on first use",
        "note": "Install to transcribe audio files locally",
    }


def report() -> dict:
    """Full capability report. Safe to call at any time; never raises."""
    try:
        import markitdown as _md
        markitdown_version = getattr(_md, "__version__", "installed")
    except ImportError:
        markitdown_version = "not installed"

    venv = os.environ.get("VIRTUAL_ENV") or str(Path(sys.executable).parent.parent)

    # Core formats always probed.
    formats: list[dict] = [_probe(f) for f in _CORE_FORMATS]

    # Optional-engine formats: probe them too but as separate rows so Diagnostics
    # can show "install OCR to enable" for missing ones.
    for f in _OCR_FORMATS:
        row = _probe_optional(f)
        formats.append(row)

    for f in _AUDIO_FORMATS:
        row = _probe_optional(f)
        formats.append(row)

    return {
        "runtime": {
            "python_version": sys.version.split()[0],
            "sidecar_version": SIDECAR_VERSION,
            "markitdown_version": markitdown_version,
            "venv_path": venv,
        },
        "formats": formats,
        "optional": {
            "ocr": _ocr_optional_status(),
            "audio": _audio_optional_status(),
        },
    }
