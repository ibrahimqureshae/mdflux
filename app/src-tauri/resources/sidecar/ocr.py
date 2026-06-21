"""
OCR engine — RapidOCR + pypdfium2 (both pip-installable, no system binary required).

RapidOCR uses ONNX Runtime; pypdfium2 rasterises PDF pages for OCR.
Both are installed together via install_engine("ocr").
"""
import importlib.util
import os
import tempfile

IMAGE_EXTENSIONS: frozenset[str] = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".tiff", ".tif", ".bmp",
})
OCR_TIMEOUT_SECS: int = 600


def is_available() -> bool:
    """
    True when RapidOCR is installed.

    Uses find_spec rather than importing — importing rapidocr_onnxruntime pulls in
    onnxruntime, whose native thread pools interfere with the sidecar's asyncio
    Proactor event loop on Windows (it stalls subprocess pipe pumping, hanging the
    first OCR request). The heavy import only ever happens inside the short-lived
    OCR worker subprocess, never in the main sidecar process.
    """
    return importlib.util.find_spec("rapidocr_onnxruntime") is not None


def has_pdf_renderer() -> bool:
    """True when pypdfium2 is available for rasterising PDF pages."""
    return importlib.util.find_spec("pypdfium2") is not None


def _make_engine(intra_op_threads: int = 0):
    """Build a RapidOCR engine, optionally limiting its onnxruntime thread count so
    concurrent batch workers don't oversubscribe the CPU. The kwarg is best-effort:
    if a RapidOCR version rejects it, fall back to the default engine."""
    from rapidocr_onnxruntime import RapidOCR
    n = int(intra_op_threads or 0)
    if n > 0:
        try:
            return RapidOCR(intra_op_num_threads=n, inter_op_num_threads=n)
        except Exception:  # noqa: BLE001 — older/newer API; use the default
            pass
    return RapidOCR()


def ocr_image(path: str, intra_op_threads: int = 0) -> str:
    """Run OCR on a single image file; return extracted text as plain text."""
    engine = _make_engine(intra_op_threads)
    result, _ = engine(path)
    if not result:
        return ""
    return "\n".join(item[1] for item in result if len(item) > 1 and item[1])


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
    Rasterise each PDF page at 150 DPI and OCR it with RapidOCR.
    Renders each page to a temp PNG via pypdfium2 + Pillow (Pillow is a transitive
    dep of rapidocr-onnxruntime, so it is always present when this function runs).
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

            bitmap = page.render(scale=150 / 72)  # 150 DPI

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name

            try:
                bitmap.to_pil().save(tmp_path)
                result, _ = engine(tmp_path)
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

            if result:
                page_text = "\n".join(
                    item[1] for item in result if len(item) > 1 and item[1]
                )
                if page_text.strip():
                    pages.append(f"## Page {i + 1}\n\n{page_text}")
    finally:
        doc.close()
    return "\n\n".join(pages) if pages else ""
