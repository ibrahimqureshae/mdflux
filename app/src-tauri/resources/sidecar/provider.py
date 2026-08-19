"""
LLM provider plumbing.

Two groups of functions:
- Health checks (`check_*`) — pure blocking, run via run_in_executor. Never send
  document content; connectivity + credentials only. Degrade gracefully (return a
  dict, never raise).
- Chat / cleanup invocation (`chat_*`, `first_model_*`) — added in Stage 5 for the
  optional LLM cleanup pass. These DO send document text and DO raise on failure, so
  the caller (cleanup.llm_clean) can fail soft and fall back to deterministic output.

Rule across both groups: never log or mention the API key in any return value.
"""
import json
import urllib.error
import urllib.request


def _safe_exc(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def check_local(base_url: str) -> dict:
    """
    Probe a local server at base_url.
    Tries Ollama (/api/tags) first, then OpenAI-compat (/v1/models).
    """
    base = base_url.rstrip("/")
    last_exc: Exception | None = None

    # Ollama: GET /api/tags
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=5) as r:
            data = json.loads(r.read())
        models: list[str] = [m.get("name", "") for m in data.get("models", [])]
        vision_kw = ("llava", "minicpm", "vision", "bakllava", "qwen-vl", "internvl", "phi3-v", "moondream")
        vision = [m for m in models if any(k in m.lower() for k in vision_kw)]
        parts = [f"{len(models)} model(s)"]
        if vision:
            parts.append(f"{len(vision)} vision-capable")
        return {
            "server": "ollama",
            "reachable": True,
            "detail": "Ollama — " + ", ".join(parts),
            "models": models,
            "usable": len(models) > 0,
        }
    except Exception as exc:
        last_exc = exc

    # OpenAI-compat: GET /v1/models (no auth required for local servers)
    try:
        with urllib.request.urlopen(f"{base}/v1/models", timeout=5) as r:
            data = json.loads(r.read())
        models = [m.get("id", "") for m in data.get("data", [])]
        return {
            "server": "openai_compat",
            "reachable": True,
            "detail": f"OpenAI-compatible server — {len(models)} model(s)",
            "models": models,
            "usable": len(models) > 0,
        }
    except Exception as exc:
        last_exc = exc

    detail = f"No server found at {base} — is Ollama or another local server running?"
    if last_exc:
        detail += f" (last error: {_safe_exc(last_exc)})"
    return {
        "server": None,
        "reachable": False,
        "detail": detail,
        "models": [],
        "usable": False,
    }


def _host_name(url: str) -> str:
    u = (url or "").lower()
    table = (
        ("openai.com", "OpenAI"),
        ("deepseek.com", "DeepSeek"),
        ("groq.com", "Groq"),
        ("anthropic.com", "Anthropic"),
        ("googleapis.com", "Google Gemini"),
        ("openrouter.ai", "OpenRouter"),
        ("together.xyz", "Together AI"),
        ("mistral.ai", "Mistral"),
        ("fireworks.ai", "Fireworks"),
        ("x.ai", "xAI"),
        ("perplexity.ai", "Perplexity"),
        ("cerebras.ai", "Cerebras"),
        ("nvidia.com", "NVIDIA"),
    )
    for needle, name in table:
        if needle in u:
            return name
    return "this endpoint"


def _401_detail(url: str) -> str:
    name = _host_name(url)
    extra = ""
    if "openai.com" in (url or "").lower():
        extra = (
            " If this key is for DeepSeek, Groq, OpenRouter, or another host, "
            "choose that provider in Diagnostics — do not leave it on OpenAI."
        )
    return f"This key was rejected by {name} (401).{extra}"


def check_openai_compat(base_url: str, key: str) -> dict:
    """Probe an OpenAI-compatible API endpoint with the supplied key."""
    base = base_url.rstrip("/")
    req = urllib.request.Request(
        f"{base}/models",
        headers={"Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
        return {
            "reachable": True,
            "detail": f"Connected to {_host_name(base)} — {len(models)} model(s) available",
            "models": models,
            "usable": True,
        }
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return {
                "reachable": True,
                "detail": _401_detail(base),
                "models": [],
                "usable": False,
            }
        return {
            "reachable": True,
            "detail": f"{_host_name(base)} returned HTTP {e.code}",
            "models": [],
            "usable": False,
        }
    except Exception as exc:
        return {
            "reachable": False,
            "detail": f"Cannot reach endpoint: {_safe_exc(exc)}",
            "models": [],
            "usable": False,
        }


def check_anthropic(key: str) -> dict:
    """Probe the Anthropic API with the supplied key."""
    if not key.startswith("sk-ant-"):
        return {
            "reachable": False,
            "detail": "Key format invalid — Anthropic keys start with 'sk-ant-'",
            "models": [],
            "usable": False,
        }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/models",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        models = [m.get("id", "") for m in data.get("data", [])]
        return {
            "reachable": True,
            "detail": f"Connected — {len(models)} model(s) available",
            "models": models,
            "usable": True,
        }
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return {
                "reachable": True,
                "detail": "Endpoint reachable — API key rejected",
                "models": [],
                "usable": False,
            }
        return {
            "reachable": True,
            "detail": f"Anthropic API returned HTTP {e.code}",
            "models": [],
            "usable": False,
        }
    except Exception as exc:
        return {
            "reachable": False,
            "detail": f"Cannot reach Anthropic API: {_safe_exc(exc)}",
            "models": [],
            "usable": False,
        }


# ── Chat / cleanup invocation (Stage 5) ─────────────────────────────────────────
# These raise on failure; the caller fails soft.

def _post_json(url: str, headers: dict, payload: dict, timeout: float) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise RuntimeError(_401_detail(url)) from None
        raise RuntimeError(f"{_host_name(url)} returned HTTP {e.code}") from None


def _assistant_text(data: dict) -> str:
    """Pull visible assistant text out of a chat-completions payload.

    Thinking models may put tokens in `reasoning_content` and leave `content`
    empty or null. Callers that need a formatter result must treat that as
    failure, not as a blank document.
    """
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("The model returned no choices.")
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        parts = [
            p.get("text", "") for p in content
            if isinstance(p, dict) and p.get("type") in (None, "text")
        ]
        joined = "".join(parts)
        if joined.strip():
            return joined
    finish = choices[0].get("finish_reason")
    raise RuntimeError(
        "The model returned no text"
        + (f" (finish_reason={finish})" if finish else "")
        + ". Try a non-reasoning chat model, or pick Auto."
    )


def chat_openai_compat(
    base_url: str, key: str, model: str, system: str, user: str, timeout: float,
    max_tokens: int | None = None,
) -> str:
    """POST {base}/chat/completions; return the assistant message content.

    `max_tokens` bounds the OUTPUT length. Leave it None to use the server default.
    Note: this endpoint cannot set the input context window — for local Ollama that
    is done via chat_ollama (the OpenAI-compat layer silently truncates over-long
    prompts at the 2048-token default).
    """
    base = base_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
    }
    if max_tokens and max_tokens > 0:
        payload["max_tokens"] = int(max_tokens)
    # DeepSeek-V4 defaults to thinking mode; reasoning tokens consume max_tokens
    # and the formatter gets an empty `content`. Cleanup is not a reasoning task.
    if "deepseek.com" in base.lower():
        payload["thinking"] = {"type": "disabled"}
    try:
        data = _post_json(f"{base}/chat/completions", headers, payload, timeout)
    except RuntimeError as exc:
        # Older DeepSeek-compatible proxies reject the thinking field.
        if payload.pop("thinking", None) is not None and "HTTP 400" in str(exc):
            data = _post_json(f"{base}/chat/completions", headers, payload, timeout)
        else:
            raise
    return _assistant_text(data)


def chat_ollama(
    base: str, model: str, system: str, user: str, timeout: float,
    num_ctx: int | None = None, num_predict: int | None = None,
) -> str:
    """POST {base}/api/chat (Ollama native). Unlike the OpenAI-compat endpoint, this
    accepts `num_ctx` — the input context window — so a long prompt is NOT silently
    truncated. `num_predict` bounds the output (use -1 for unbounded)."""
    options: dict = {"temperature": 0}
    if num_ctx:
        options["num_ctx"] = int(num_ctx)
    if num_predict is not None:
        options["num_predict"] = int(num_predict)
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": options,
    }
    data = _post_json(f"{base}/api/chat", {"Content-Type": "application/json"}, payload, timeout)
    return data.get("message", {}).get("content", "")


def chat_local(
    base_url: str, model: str, system: str, user: str, timeout: float,
    num_ctx: int | None = None, num_predict: int | None = None,
) -> str:
    """Local chat. Prefers Ollama's native /api/chat so we can set `num_ctx` and avoid
    silent prompt truncation; falls back to the OpenAI-compatible endpoint (LM Studio,
    Jan, etc.) where the context window is fixed at model-load time instead.
    """
    base = base_url.rstrip("/")
    # Try Ollama native first (only it honours num_ctx). A non-Ollama server returns
    # 404/connection error here, so we fall through to the OpenAI-compat path.
    native_exc: Exception | None = None
    try:
        out = chat_ollama(base, model, system, user, timeout, num_ctx, num_predict)
        if out:
            return out
    except Exception as exc:  # noqa: BLE001 — not Ollama, or transient; try the compat path
        native_exc = exc
    last: Exception | None = None
    out_cap = num_predict if (num_predict and num_predict > 0) else None
    for candidate in (f"{base}/v1", base):
        try:
            return chat_openai_compat(candidate, "", model, system, user, timeout, out_cap)
        except Exception as exc:  # noqa: BLE001
            last = exc
    # If both paths failed, prefer the native error (usually more informative:
    # "model not found", etc.) over the compat error.
    raise native_exc or last or RuntimeError("Local chat failed")


def chat_anthropic(
    key: str, model: str, system: str, user: str, timeout: float,
    max_tokens: int = 8192,
) -> str:
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": int(max_tokens),
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    data = _post_json("https://api.anthropic.com/v1/messages", headers, payload, timeout)
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return "".join(parts)


def _pick_cleanup_model(models: list[str]) -> str:
    """Prefer a fast chat/flash model; skip dedicated reasoners for cleanup."""
    skip = ("reasoner", "o1-", "o3-", "o4-")
    scored: list[tuple[int, str]] = []
    for m in models:
        low = m.lower()
        if any(s in low for s in skip):
            continue
        score = 0
        if any(k in low for k in ("flash", "chat", "mini", "haiku", "turbo")):
            score += 2
        if "pro" in low:
            score -= 1
        scored.append((score, m))
    scored.sort(key=lambda x: -x[0])
    return scored[0][1] if scored else models[0]


def first_model_openai_compat(base_url: str, key: str) -> str:
    res = check_openai_compat(base_url, key)
    models = res.get("models") or []
    if not models:
        raise RuntimeError("No models available from the configured endpoint.")
    return _pick_cleanup_model(models)


def first_model_anthropic(key: str) -> str:
    res = check_anthropic(key)
    models = res.get("models") or []
    if not models:
        raise RuntimeError("No models available from the Anthropic API.")
    return models[0]


def first_model_local(base_url: str) -> str:
    res = check_local(base_url)
    models = res.get("models") or []
    if not models:
        raise RuntimeError("No models available from the local server.")
    return models[0]
