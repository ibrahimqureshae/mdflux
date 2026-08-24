from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path


SIDECAR_DIR = Path(__file__).resolve().parents[1]
if str(SIDECAR_DIR) not in sys.path:
    sys.path.insert(0, str(SIDECAR_DIR))

OCR_AVAILABLE = importlib.util.find_spec("rapidocr") is not None


def setUpModule() -> None:
    if os.environ.get("MDFLUX_REQUIRE_OCR_TESTS") == "1" and not OCR_AVAILABLE:
        raise AssertionError("Locked OCR integration tests require rapidocr")


@unittest.skipUnless(OCR_AVAILABLE, "rapidocr is not installed in the core test environment")
class LockedOcrRuntimeTests(unittest.TestCase):
    def test_image_and_scanned_pdf_ocr(self) -> None:
        from PIL import Image, ImageDraw, ImageFont

        import ocr

        with tempfile.TemporaryDirectory(prefix="mdflux-ocr-test-") as tmp:
            root = Path(tmp)
            image_path = root / "ocr-test.png"
            pdf_path = root / "ocr-test-scanned.pdf"
            image = Image.new("RGB", (1400, 360), "white")
            font = ImageFont.load_default(size=72)
            ImageDraw.Draw(image).text(
                (60, 120),
                "MDFlux OCR integration test 2026",
                fill="black",
                font=font,
                stroke_width=1,
            )
            image.save(image_path)
            image.save(pdf_path, "PDF", resolution=150.0)

            image_text = ocr.ocr_image(str(image_path), intra_op_threads=1)
            self.assertTrue(image_text.strip(), "Image OCR returned no text")

            self.assertTrue(ocr.is_scanned_pdf(str(pdf_path)))
            pdf_text = ocr.ocr_pdf(str(pdf_path), intra_op_threads=1)
            self.assertTrue(pdf_text.strip(), "Scanned-PDF OCR returned no text")
            self.assertIn("## Page 1", pdf_text)


if __name__ == "__main__":
    unittest.main()
