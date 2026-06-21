"""
Markdown cleanup — pure deterministic post-process, plus an optional LLM pass.

Design (Stage 5):
- `clean(markdown, source_format, rules)` is a PURE function: raw Markdown in,
  cleaned Markdown out, plus a structured per-rule change summary. No model, no
  network, deterministic, fast, fully unit-testable against fixtures.
- Each rule is independently toggleable via the `rules` dict. The ORDER in which
  rules run is fixed (RULE_ORDER) regardless of which are enabled.
- The function never mutates anything on disk; the caller retains the raw text, so
  cleanup is always reversible.
- `llm_clean(text, provider_cfg)` runs AFTER the deterministic pass when the user
  opts in. It reuses provider.py's chat plumbing and FAILS SOFT — on any error it
  raises, and the caller falls back to the deterministic output with a notice.

The rules target documented MarkItDown PDF pain points:
  strip_cid       — remove (cid:N) glyph markers
  dedup_lines     — drop repeated header/footer / duplicated lines
  repair_lines    — rejoin sentences split across lines by column/page breaks
  collapse_blanks — normalise runs of blank lines
  detect_headings — conservatively promote heading-like lines to Markdown headings
"""
import re

import provider as _provider

# Fixed deterministic order. Each rule applies only if enabled in `rules`.
RULE_ORDER: list[str] = [
    "strip_cid",
    "dedup_lines",
    "repair_lines",
    "collapse_blanks",
    "detect_headings",
]

RULE_LABELS: dict[str, str] = {
    "strip_cid": "Removed (cid:N) markers",
    "dedup_lines": "Removed duplicate lines",
    "repair_lines": "Rejoined broken lines",
    "collapse_blanks": "Collapsed blank runs",
    "detect_headings": "Detected headings",
}

# The LLM cleans the document in CHUNKS so the prompt never overflows the model's
# context window. Overflow is the #1 cause of "the AI truncated my document": a local
# server (Ollama) silently drops the FRONT of an over-long prompt — at its 2048-token
# default — so the model only sees a fragment and returns something far shorter (often
# a summary). Each chunk is sized to fit comfortably, and for local models we ALSO set
# the context window explicitly per request (see provider.chat_local / chat_ollama).
_CHUNK_TARGET_CHARS: int = 8_000     # ~2,000 tokens of input per request
_NUM_CTX_MAX: int = 16_384           # cap on the local context window we request
_NUM_CTX_FLOOR: int = 2_048
_CHARS_PER_TOKEN: int = 4            # rough English estimate for sizing only

# Data-loss guardrail. The LLM is asked only to fix formatting, never to summarise
# or drop content — but small models routinely ignore that. After the LLM responds
# we verify it preserved the input's content; if not, we warn the user (advisory).
LLM_MIN_WORD_RECALL: float = 0.85   # below this, warn the user (advisory, not enforced)
LLM_MIN_LENGTH_RATIO: float = 0.6   # below this fraction of input length, warn the user

# System instruction — framed as a formatter, applied per chunk.
_SYSTEM_PROMPT: str = (
    "You are a text-formatting tool, not an assistant. You receive Markdown that "
    "was extracted from a document and you return a corrected copy of it.\n"
    "Make ONLY these changes:\n"
    "- repair Markdown structure: headings, lists, tables, paragraph spacing\n"
    "- remove obvious extraction artifacts and stray characters\n"
    "Hard rules you must obey:\n"
    "- Output ONLY the corrected Markdown. No preamble, no explanation, no "
    "commentary, no quoting, no surrounding code fences.\n"
    "- NEVER summarise, shorten, reword, translate, reorder, or omit any content.\n"
    "- Preserve every sentence, number, heading, and line of content.\n"
    "- If nothing needs fixing, return the input unchanged."
)


class CleanupCancelled(Exception):
    """Raised inside the worker thread when the caller cancels mid-document."""

_CID_RE = re.compile(r"\(cid:\d+\)")
_STRUCTURAL_RE = re.compile(r"^\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|>|\||```|~~~)")
_NUMBERED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+\S")
_TERMINAL_PUNCT = (".", ",", ";", ":", "!", "?")


# ── Public API ─────────────────────────────────────────────────────────────────

def clean(markdown: str, source_format: str, rules: dict) -> tuple[str, dict]:
    """Apply the enabled deterministic rules in fixed order.

    Returns (cleaned_markdown, summary). `summary` has the shape:
      {
        "rules": [{"key","label","applied","changes"}, ...],   # one per RULE_ORDER
        "char_delta": int,   # cleaned_len - raw_len (negative = shrank)
        "line_delta": int,
      }
    """
    raw_chars = len(markdown)
    raw_lines = markdown.count("\n") + 1
    text = markdown
    rule_summaries: list[dict] = []

    for key in RULE_ORDER:
        enabled = bool(rules.get(key, False))
        changes = 0
        if enabled:
            text, changes = _RULES[key](text)
        rule_summaries.append({
            "key": key,
            "label": RULE_LABELS[key],
            "applied": enabled,
            "changes": changes,
        })

    summary = {
        "rules": rule_summaries,
        "char_delta": len(text) - raw_chars,
        "line_delta": (text.count("\n") + 1) - raw_lines,
    }
    return text, summary


def llm_clean(
    text: str,
    provider_cfg: dict,
    timeout: float = 120.0,
    progress_cb=None,
    should_cancel=None,
) -> str:
    """Run an LLM cleanup pass, CHUNKED so no single request overflows the model's
    context window. Reuses provider.py plumbing; raises on failure (caller fails soft).

    `provider_cfg`: {mode, api_type, base_url, key, model}.
    `progress_cb(done, total)`: optional, called as each chunk completes (thread-safe
        ints only — it's invoked from the executor thread).
    `should_cancel()`: optional predicate; checked between chunks. Returns truthy to
        stop early (raises CleanupCancelled).
    """
    mode = provider_cfg.get("mode", "off")
    model = (provider_cfg.get("model") or "").strip()
    base_url = provider_cfg.get("base_url", "")
    key = provider_cfg.get("key", "")
    api_type = provider_cfg.get("api_type", "openai_compat")

    # Short-circuit: an empty document would still trigger model resolution +
    # one LLM chunk call with an empty user message — wasteful. Fire BEFORE
    # _resolve_model so no network call is made for empty input.
    if not text.strip():
        return text

    # Resolve the model once, not per chunk.
    if not model:
        model = _resolve_model(mode, api_type, base_url, key)

    chunks = _split_into_chunks(text, _CHUNK_TARGET_CHARS)
    total = len(chunks)
    if progress_cb:
        progress_cb(0, total)

    cleaned_parts: list[str] = []
    for i, chunk in enumerate(chunks):
        if should_cancel and should_cancel():
            raise CleanupCancelled()
        out = _clean_one_chunk(chunk, mode, api_type, base_url, key, model, timeout)
        cleaned_parts.append(out.strip("\n"))
        if progress_cb:
            progress_cb(i + 1, total)

    return "\n\n".join(p for p in cleaned_parts if p)


def data_loss_warning(original: str, candidate: str) -> str | None:
    """Advisory check (NOT enforced): if the AI output looks like it dropped or
    rewrote content, return a warning string for the UI to show. The AI result is
    still presented — the user decides whether to keep it. Returns None if it looks
    faithful."""
    if not candidate or not candidate.strip():
        return None  # emptiness is handled by the caller as a hard failure

    olen, clen = len(original), len(candidate)
    if olen > 0 and clen < LLM_MIN_LENGTH_RATIO * olen:
        pct = round((1 - clen / olen) * 100)
        return (
            f"The AI result is about {pct}% shorter than the original — it may have "
            "dropped content (common with large files on local models). Compare with "
            "Original / Changes before saving, or try a larger model or API mode."
        )

    orig_words = _content_words(original)
    if orig_words:
        kept = orig_words & _content_words(candidate)
        recall = len(kept) / len(orig_words)
        if recall < LLM_MIN_WORD_RECALL:
            return (
                "The AI may have changed or dropped some content. Compare with "
                "Original / Changes before saving."
            )
    return None


def _resolve_model(mode, api_type, base_url, key) -> str:
    if mode == "api" and api_type == "anthropic":
        return _provider.first_model_anthropic(key)
    if mode == "local":
        return _provider.first_model_local(base_url)
    return _provider.first_model_openai_compat(base_url, key)


def _est_tokens(s: str) -> int:
    return max(1, len(s) // _CHARS_PER_TOKEN)


def _round_up(n: int, step: int) -> int:
    return ((n + step - 1) // step) * step


def _clean_one_chunk(chunk, mode, api_type, base_url, key, model, timeout) -> str:
    """Send one chunk to the model with a context window / output cap sized to fit it,
    so the prompt is never silently truncated."""
    system = _SYSTEM_PROMPT
    # A faithful copy is roughly the same length as the input, plus headroom for any
    # added structure. Budget output ~1.5x the chunk's tokens.
    out_budget = int(_est_tokens(chunk) * 1.5) + 256

    if mode == "api" and api_type == "anthropic":
        return _provider.chat_anthropic(key, model, system, chunk, timeout,
                                        max_tokens=min(8192, out_budget))

    if mode == "local":
        in_tok = _est_tokens(system) + _est_tokens(chunk)
        num_ctx = _round_up(in_tok + out_budget + 256, 2048)
        num_ctx = max(_NUM_CTX_FLOOR, min(num_ctx, _NUM_CTX_MAX))
        return _provider.chat_local(base_url, model, system, chunk, timeout,
                                    num_ctx=num_ctx, num_predict=out_budget)

    # api, openai-compatible (OpenAI, Groq, …) — large fixed context; cap the output.
    return _provider.chat_openai_compat(base_url, key, model, system, chunk, timeout,
                                        max_tokens=out_budget)


def _split_into_chunks(text: str, target_chars: int) -> list[str]:
    """Split Markdown into chunks of <= ~target_chars on block boundaries (blank lines),
    keeping fenced code blocks and tables intact. A single block larger than the target
    becomes its own chunk rather than being split mid-structure."""
    lines = text.split("\n")
    blocks: list[str] = []
    cur: list[str] = []
    in_fence = False
    fence: str | None = None

    for line in lines:
        stripped = line.lstrip()
        is_fence = stripped.startswith("```") or stripped.startswith("~~~")
        if is_fence:
            marker = stripped[:3]
            if not in_fence:
                in_fence, fence = True, marker
            elif fence and stripped.startswith(fence):
                in_fence, fence = False, None
            cur.append(line)
            continue
        if line.strip() == "" and not in_fence:
            if cur:
                blocks.append("\n".join(cur))
                cur = []
        else:
            cur.append(line)
    if cur:
        blocks.append("\n".join(cur))

    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    for b in blocks:
        blen = len(b) + 2
        if buf and size + blen > target_chars:
            chunks.append("\n\n".join(buf))
            buf, size = [], 0
        buf.append(b)
        size += blen
    if buf:
        chunks.append("\n\n".join(buf))

    return chunks if chunks else [text]


def _content_words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{4,}", text.lower()))


# ── Rule implementations ────────────────────────────────────────────────────────
# Each returns (new_text, change_count).

def _rule_strip_cid(text: str) -> tuple[str, int]:
    count = len(_CID_RE.findall(text))
    if not count:
        return text, 0
    out = _CID_RE.sub("", text)
    # Tidy doubled spaces left behind, line by line (don't touch leading indent).
    lines = []
    for line in out.split("\n"):
        stripped = re.sub(r"[ \t]{2,}", " ", line)
        lines.append(stripped.rstrip() if stripped.strip() else line)
    return "\n".join(lines), count


def _rule_dedup_lines(text: str) -> tuple[str, int]:
    lines = text.split("\n")

    # Pass A: collapse immediate consecutive duplicate non-empty lines.
    deduped: list[str] = []
    removed = 0
    for line in lines:
        if line.strip() and deduped and deduped[-1] == line:
            removed += 1
            continue
        deduped.append(line)

    # Pass B: drop repeated short running heads / footers / page numbers — lines that
    # recur >= 3 times across the doc and are short. Keep the first occurrence.
    counts: dict[str, int] = {}
    for line in deduped:
        s = line.strip()
        if s and len(s) <= 80:
            counts[s] = counts.get(s, 0) + 1
    frequent = {s for s, c in counts.items() if c >= 3}

    result: list[str] = []
    seen: set[str] = set()
    for line in deduped:
        s = line.strip()
        if s in frequent:
            if s in seen:
                removed += 1
                continue
            seen.add(s)
        result.append(line)

    return "\n".join(result), removed


def _rule_repair_lines(text: str) -> tuple[str, int]:
    lines = text.split("\n")
    out: list[str] = []
    joins = 0

    for line in lines:
        if not out:
            out.append(line)
            continue

        prev = out[-1]
        if _can_join(prev, line):
            if prev.rstrip().endswith("-") and not prev.rstrip().endswith("--"):
                # De-hyphenate: "exam-" + "ple" -> "example"
                out[-1] = prev.rstrip()[:-1] + line.lstrip()
            else:
                out[-1] = prev.rstrip() + " " + line.lstrip()
            joins += 1
        else:
            out.append(line)

    return "\n".join(out), joins


def _can_join(prev: str, cur: str) -> bool:
    p, c = prev.strip(), cur.strip()
    if not p or not c:
        return False
    if _STRUCTURAL_RE.match(prev) or _STRUCTURAL_RE.match(cur):
        return False
    # Previous line already ends a sentence/block → leave the break.
    if p.endswith(_TERMINAL_PUNCT):
        # Exception: a trailing hyphen means a split word.
        if not p.endswith("-"):
            return False
    # Continuation looks like a new sentence/proper start → don't merge.
    first = c[0]
    if first.isupper() or first.isdigit():
        return False
    return True


def _rule_collapse_blanks(text: str) -> tuple[str, int]:
    lines = text.split("\n")
    out: list[str] = []
    blanks = 0
    removed = 0
    for line in lines:
        if line.strip() == "":
            blanks += 1
            if blanks <= 1:
                out.append(line)
            else:
                removed += 1
        else:
            blanks = 0
            out.append(line)
    return "\n".join(out), removed


def _rule_detect_headings(text: str) -> tuple[str, int]:
    lines = text.split("\n")
    n = len(lines)
    promoted = 0

    def blank_or_edge(i: int) -> bool:
        return i < 0 or i >= n or lines[i].strip() == ""

    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        # Must be visually isolated (blank or document edge on both sides).
        if not (blank_or_edge(i - 1) and blank_or_edge(i + 1)):
            continue
        if _STRUCTURAL_RE.match(line):
            continue
        if len(s) > 60 or len(s.split()) > 10:
            continue
        if s.endswith((".", ",", ";", ":")):
            continue

        m = _NUMBERED_HEADING_RE.match(s)
        if m:
            depth = m.group(1).count(".") + 1
            level = "###" if depth >= 2 else "##"
            lines[i] = f"{level} {s}"
            promoted += 1
            continue

        if _is_titleish(s):
            lines[i] = f"## {s}"
            promoted += 1

    return "\n".join(lines), promoted


def _is_titleish(s: str) -> bool:
    letters = [ch for ch in s if ch.isalpha()]
    if not letters:
        return False
    # ALL CAPS (short heading shout) — strong signal.
    if s.upper() == s and any(ch.isalpha() for ch in s):
        return True
    # Title Case: most significant words start uppercase.
    words = [w for w in re.split(r"\s+", s) if any(ch.isalpha() for ch in w)]
    if len(words) < 2:
        return False
    minor = {"a", "an", "the", "of", "and", "or", "to", "in", "on", "for", "with"}
    significant = [w for w in words if w.lower() not in minor]
    if not significant:
        return False
    capped = sum(1 for w in significant if w[0].isupper())
    return capped / len(significant) >= 0.8


_RULES = {
    "strip_cid": _rule_strip_cid,
    "dedup_lines": _rule_dedup_lines,
    "repair_lines": _rule_repair_lines,
    "collapse_blanks": _rule_collapse_blanks,
    "detect_headings": _rule_detect_headings,
}
