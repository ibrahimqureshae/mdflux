"""Pre-flight checks run before spawning the conversion worker."""
import os
import sys

from errors import ENCRYPTED_INPUT, FILE_TOO_LARGE, FILE_UNREADABLE, err

MAX_FILE_BYTES: int = 100 * 1024 * 1024  # 100 MB
# Cloud placeholder files (OneDrive Files On-Demand) report their logical size but
# aren't downloaded yet. They get a longer timeout in main.py, so allow larger ones.
MAX_CLOUD_FILE_BYTES: int = 500 * 1024 * 1024  # 500 MB


def _is_cloud_placeholder(path: str) -> bool:
    if sys.platform != "win32":
        return False
    try:
        attrs = os.stat(path).st_file_attributes
    except (OSError, AttributeError):
        return False
    return bool(attrs & (0x00040000 | 0x00400000 | 0x00001000))


def check(path: str, ext: str) -> dict | None:
    """Return a typed error dict if the file must not be converted, else None."""

    if not os.access(path, os.R_OK):
        return err(
            FILE_UNREADABLE,
            "File not readable",
            f"'{os.path.basename(path)}' can't be opened — permission denied or file is locked.",
            "Close any app that has the file open, check permissions, and try again.",
        )

    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0

    # Cloud placeholders get a higher size limit — they'll be downloaded on read
    # and the longer timeout in main.py accommodates the download.
    limit = MAX_CLOUD_FILE_BYTES if _is_cloud_placeholder(path) else MAX_FILE_BYTES
    if size > limit:
        mb = size / (1024 * 1024)
        limit_mb = limit // (1024 * 1024)
        return err(
            FILE_TOO_LARGE,
            "File is too large",
            f"This file is {mb:.1f} MB — the limit is {limit_mb} MB.",
            "Split the file or export a smaller selection, then try again.",
        )

    # Encrypted PDF: scan for the /Encrypt entry. It lives in the trailer dictionary,
    # which sits at the END of the file — so checking only the head (as before) missed
    # most real encrypted PDFs. Scan both the first and last 64 KB to cover linearized
    # PDFs (Encrypt referenced early) and ordinary ones (Encrypt in the trailer).
    if ext == ".pdf":
        try:
            scan_len = 65536
            with open(path, "rb") as f:
                head = f.read(scan_len)
                if size > scan_len:
                    f.seek(max(0, size - scan_len))
                    tail = f.read(scan_len)
                else:
                    tail = b""
            if b"/Encrypt" in head or b"/Encrypt" in tail:
                return err(
                    ENCRYPTED_INPUT,
                    "PDF is password-protected",
                    "This PDF is encrypted and can't be read without the password.",
                    "Unlock it in Preview (Mac) or Adobe Acrobat, then try again.",
                )
        except OSError:
            pass  # readability check above already handles this

    return None
