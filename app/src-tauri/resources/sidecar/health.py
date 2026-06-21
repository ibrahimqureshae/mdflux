"""Health-check: probes Python version, markitdown core, and each format extra.

The EXTRAS map is derived from capabilities._CORE_FORMATS so the two cannot drift
(see the Stage 3 review: health had an 'outlook' entry that capabilities didn't).
"""
import sys
import importlib

import capabilities as _caps


def _extras_map() -> dict[str, str]:
    return {
        f["key"]: f["module"]
        for f in _caps._CORE_FORMATS
        if f.get("module")
    }


def check() -> dict:
    result = {
        "python_version": sys.version.split()[0],
        "markitdown_version": None,
        "extras": {},
    }

    try:
        import markitdown
        result["markitdown_version"] = getattr(markitdown, "__version__", "installed")
    except ImportError:
        pass

    for name, module in _extras_map().items():
        try:
            importlib.import_module(module)
            result["extras"][name] = True
        except ImportError:
            result["extras"][name] = False

    return result
