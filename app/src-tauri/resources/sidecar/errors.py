"""Typed error codes and envelope builder for IPC v1."""


UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
MISSING_EXTRA      = "MISSING_EXTRA"
FILE_NOT_FOUND     = "FILE_NOT_FOUND"
FILE_UNREADABLE    = "FILE_UNREADABLE"
CONVERSION_FAILED  = "CONVERSION_FAILED"
INTERNAL_ERROR     = "INTERNAL_ERROR"
TIMEOUT            = "TIMEOUT"
CANCELLED          = "CANCELLED"
ENCRYPTED_INPUT    = "ENCRYPTED_INPUT"
FILE_TOO_LARGE     = "FILE_TOO_LARGE"


def err(code: str, title: str, detail: str, suggested_action: str) -> dict:
    return {
        "ok": False,
        "error": {
            "code": code,
            "title": title,
            "detail": detail,
            "suggested_action": suggested_action,
        },
    }
