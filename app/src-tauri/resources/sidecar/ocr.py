"""
OCR engine — RapidOCR 3 + pypdfium2 (both pip-installable, no system binary required).

RapidOCR 3.9+ defaults to Baidu PP-OCRv6 small (ONNX Runtime). Models ship inside the
pinned `rapidocr` wheel, so install stays offline after the hash-verified pip step.
pypdfium2 rasterises PDF pages for OCR.
"""
import importlib.util
import os
import tempfile

from pathlib import Path

IMAGE_EXTENSIONS: frozenset[str] = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".tiff", ".tif", ".bmp",
})
OCR_TIMEOUT_SECS: int = 600


def is_available() -> bool:
    """
    True when RapidOCR is installed.

    Uses find_spec rather than importing — importing RapidOCR pulls in
    onnxruntime, whose native thread pools interfere with the sidecar's asyncio
    Proactor event loop on Windows (it stalls subprocess pipe pumping, hanging the
    first OCR request). The heavy import only ever happens inside the short-lived
    OCR worker subprocess, never in the main sidecar process.
    """
    return (
        importlib.util.find_spec("rapidocr") is not None
        or importlib.util.find_spec("rapidocr_onnxruntime") is not None
    )


def has_pdf_renderer() -> bool:
    """True when pypdfium2 is available for rasterising PDF pages."""
    return importlib.util.find_spec("pypdfium2") is not None


def _make_engine(intra_op_threads: int = 0):
    """Build a RapidOCR engine, optionally limiting onnxruntime threads so
    concurrent batch workers don't oversubscribe the CPU."""
    n = int(intra_op_threads or 0)
    if importlib.util.find_spec("rapidocr") is not None:
        import rapidocr
        from rapidocr import RapidOCR

        # WORKAROUND (v0.3.0): the bundled omegaconf==2.0.6 rejects pathlib.Path
        # values ("Value 'WindowsPath' is not a supported primitive type"), and
        # RapidOCR assigns a Path into Global.model_root_dir when it is unset.
        # Pre-set it as a plain string pointing at the models bundled inside the
        # rapidocr wheel; RapidOCR wraps it back into a Path before loading models.
        models_dir = str(Path(rapidocr.__file__).resolve().parent / "models")

        # NOTE: do NOT pass Det./Rec. ocr_version/model_type as strings here —
        # RapidOCR requires Enum types for those keys. Its built-in defaults
        # already pin PP-OCRv6 + small for Det/Rec, so omitting them is correct.
        params: dict = {
            "Global.log_level": "warning",
            "Global.model_root_dir": models_dir,
        }
        if n > 0:
            params["EngineConfig.onnxruntime.intra_op_num_threads"] = n
            params["EngineConfig.onnxruntime.inter_op_num_threads"] = n
        try:
            return RapidOCR(params=params)
        except Exception:  # noqa: BLE001 — older/newer keys; use defaults
            return RapidOCR(params=params)

    from rapidocr_onnxruntime import RapidOCR
    if n > 0:
        try:
            return RapidOCR(intra_op_num_threads=n, inter_op_num_threads=n)
        except Exception:  # noqa: BLE001
            pass
    return RapidOCR()


def _result_text(result) -> str:
    """Pull reading-order text from RapidOCR 3 output, with a v1 list fallback."""
    txts = getattr(result, "txts", None)
    if txts:
        to_md = getattr(result, "to_markdown", None)
        if callable(to_md):
            md = to_md()
            if md and "没有检测" not in md:
                return md
        return "\n".join(t for t in txts if t and str(t).strip())
    if not result:
        return ""
    # rapidocr-onnxruntime 1.x: list of [box, text, score]
    lines = []
    for item in result:
        if len(item) > 1 and item[1]:
            lines.append(item[1])
    return "\n".join(lines)


def ocr_image(path: str, intra_op_threads: int = 0) -> str:
    """Run OCR on a single image file; return extracted text as plain text."""
    engine = _make_engine(intra_op_threads)
    return _result_text(engine(path))


def is_scanned_pdf(path: str) -> bool:
    """
    Heuristic: fewer than ~30 characters of extractable text per page → probably a
    scanned or image-only PDF.

    Uses pypdfium2 page-by-page with an EARLY EXIT: a normal text PDF crosses the text
    threshold within the first page or two and returns immediately, instead of parsing
    up to 10 pages every time (this check runs for every PDF when OCR is installed).
    Falls back to pdfminer only if pypdfium2 isn't present.
    """
    if has_pdf_renderer():
        try:
            import pypdfium2 as pdfium
            doc = pdfium.PdfDocument(path)
            try:
                sample = min(len(doc), 10) or 1
                threshold = sample * 30
                total = 0
                for i in range(sample):
                    textpage = doc[i].get_textpage()
                    total += len(textpage.get_text_range().strip())
                    if total >= threshold:
                        return False  # clearly has text — bail without reading the rest
                return total < threshold
            finally:
                doc.close()
        except Exception:
            return False

    try:
        import pdfminer.high_level as pm
        text = pm.extract_text(path, maxpages=10)
        return len(text.strip()) < 10 * 30
    except Exception:
        return False


def ocr_pdf(path: str, progress_cb=None, intra_op_threads: int = 0) -> str:
    """
    Rasterise each PDF page at 220 DPI and OCR it with RapidOCR.
    Renders each page to a temp PNG via pypdfium2 + Pillow (Pillow is a transitive
    dep of RapidOCR, so it is always present when this function runs).
    progress_cb(frac, stage_str) called per page.
    """
    import pypdfium2 as pdfium

    engine = _make_engine(intra_op_threads)
    doc = pdfium.PdfDocument(path)
    n = len(doc)
    pages: list[str] = []

    try:
        for i in range(n):
            page = doc[i]
            if progress_cb:
                progress_cb(i / n, f"OCR page {i + 1}/{n}")

            bitmap = page.render(scale=220 / 72)  # 220 DPI — sharper than 150, still faster than 300

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name

            try:
                bitmap.to_pil().save(tmp_path)
                text = _result_text(engine(tmp_path))
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

            if text.strip():
                pages.append(f"## Page {i + 1}\n\n{text.strip()}")
    finally:
        doc.close()
    return "\n\n".join(pages) if pages else ""
