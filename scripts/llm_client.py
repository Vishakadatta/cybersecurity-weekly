"""
Provider-agnostic LLM client with task-based model routing.

Backends (Western/allied-origin only):
- Groq (Meta Llama 4 Scout, Llama 3.3 70B, Llama 3.1 8B)
- Gemini 3 Flash / 3.1 Flash-Lite (last resort)

Each task maps to a specific model fallback chain. The editorial/synthesis
chain never contains 8B — enforced by assertion.
"""

import json
import os
import re
import sys
import time

# ---------------------------------------------------------------------------
# Task → model routing table (CO §7)
# ---------------------------------------------------------------------------
# Each task defines a chain of (backend, model) pairs tried in order.
# "groq" models are tried before any "gemini" model per project policy.

TASK_CHAINS: dict[str, list[tuple[str, str]]] = {
    "discovery": [
        ("groq", "llama-3.1-8b-instant"),
        ("groq", "meta-llama/llama-4-scout-17b-16e-instruct"),
    ],
    "summarize": [
        ("groq", "meta-llama/llama-4-scout-17b-16e-instruct"),
        ("groq", "llama-3.3-70b-versatile"),
    ],
    "editorial": [
        ("groq", "llama-3.3-70b-versatile"),
        ("groq", "meta-llama/llama-4-scout-17b-16e-instruct"),
        ("gemini", "gemini-3-flash"),
    ],
    "verify": [
        ("groq", "meta-llama/llama-4-scout-17b-16e-instruct"),
        ("groq", "llama-3.3-70b-versatile"),
    ],
    "emergency": [
        ("groq", "meta-llama/llama-4-scout-17b-16e-instruct"),
        ("gemini", "gemini-3-flash"),
    ],
}

# Hard constraint: 8B must never appear in editorial/finalize chains.
for _task in ("editorial", "verify"):
    for _be, _model in TASK_CHAINS[_task]:
        assert "8b" not in _model.lower(), f"8B model in {_task} chain: {_model}"

GEMINI_MODELS = [
    "gemini-3-flash",
    "gemini-3.1-flash-lite",
]

DEFAULT_DELAY = 5
REQUEST_DELAY = int(os.environ.get("LLM_DELAY_SECONDS", str(DEFAULT_DELAY)))
MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "2"))


class ProjectError(Exception):
    """Unrecoverable error (bad key, banned project, spending cap)."""


class QuotaExhausted(Exception):
    """Daily quota exhausted for a model — caller should checkpoint and exit 0."""
    def __init__(self, model: str, scope: str = "daily"):
        self.model = model
        self.scope = scope
        super().__init__(f"Quota exhausted for {model} ({scope})")


# ---------------------------------------------------------------------------
# Rate-limit budget tracking (from Groq response headers)
# ---------------------------------------------------------------------------

_budget: dict[str, dict] = {}


def get_budget() -> dict[str, dict]:
    return dict(_budget)


def _update_budget_from_headers(model: str, headers: dict):
    info = {}
    for key, field in [
        ("x-ratelimit-remaining-requests", "remaining_requests"),
        ("x-ratelimit-remaining-tokens", "remaining_tokens"),
        ("retry-after", "retry_after"),
        ("x-ratelimit-reset-requests", "reset_requests"),
        ("x-ratelimit-reset-tokens", "reset_tokens"),
    ]:
        val = headers.get(key)
        if val is not None:
            try:
                info[field] = int(val) if field.startswith("remaining") else val
            except (ValueError, TypeError):
                info[field] = val
    if info:
        _budget[model] = info


def _check_budget_before_call(model: str, min_tokens: int = 2000):
    b = _budget.get(model)
    if not b:
        return
    remaining = b.get("remaining_tokens")
    if remaining is not None and remaining < min_tokens:
        raise QuotaExhausted(model, "daily-tokens-low")


def _parse_json(text: str):
    cleaned = (text or "").strip()
    fence = re.match(r"^```(?:json)?\s*\n?(.*?)```\s*$", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def _classify_error(e: Exception) -> str:
    msg = str(e).lower()
    if any(p in msg for p in [
        "api key expired", "api_key_invalid", "api key not valid",
        "invalid api key", "permission denied", "project has been deleted",
        "account is inactive", "unauthorized",
    ]):
        return "project"
    if "spending cap" in msg and "429" in msg:
        return "project"
    if "429" in msg or "resource_exhausted" in msg or "rate limit" in msg:
        if "limit: 0" in msg:
            return "model_404"
        # Check for daily exhaustion markers
        if any(w in msg for w in ["daily", "day", "24h"]):
            return "daily_limit"
        return "rate_limit"
    if "404" in msg or "not found" in msg or "model_not_found" in msg:
        return "model_404"
    return "transient"


# ---------- Groq backend ----------

_groq_client = None


def _get_groq_client():
    global _groq_client
    if _groq_client is not None:
        return _groq_client
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None
    try:
        from groq import Groq
    except ImportError:
        print("  [groq] SDK not installed (pip install groq)", flush=True)
        return None
    _groq_client = Groq(api_key=api_key)
    return _groq_client


def _groq_generate(prompt: str, model: str, temperature: float):
    client = _get_groq_client()
    if client is None:
        raise RuntimeError("Groq backend unavailable (no key or SDK)")

    _check_budget_before_call(model)

    for attempt in range(MAX_RETRIES + 1):
        try:
            print(f"  [groq:{model} attempt {attempt + 1}/{MAX_RETRIES + 1}]", end=" ", flush=True)
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            # Parse rate-limit headers from the raw response if available
            raw_resp = getattr(resp, "_raw_response", None) or getattr(resp, "http_response", None)
            if raw_resp and hasattr(raw_resp, "headers"):
                _update_budget_from_headers(model, dict(raw_resp.headers))

            text = resp.choices[0].message.content
            parsed = _parse_json(text)
            if parsed is None:
                print("JSON parse failed, retrying...", flush=True)
                if attempt < MAX_RETRIES:
                    time.sleep(10)
                    continue
                return None
            print("OK", flush=True)
            return parsed
        except Exception as e:
            kind = _classify_error(e)
            preview = str(e)[:150]
            if kind == "project":
                print(f"\n  FATAL: {preview}", flush=True)
                raise ProjectError(str(e)) from e
            if kind == "daily_limit":
                print(f"daily quota exhausted", flush=True)
                raise QuotaExhausted(model, "daily") from e
            if kind == "model_404":
                print(f"not available", flush=True)
                return None
            if kind == "rate_limit":
                if attempt < MAX_RETRIES:
                    wait = 30 * (attempt + 1)
                    print(f"rate-limited, waiting {wait}s...", flush=True)
                    time.sleep(wait)
                else:
                    print(f"exhausted retries", flush=True)
                    return None
            else:
                print(f"error: {preview}", flush=True)
                if attempt < MAX_RETRIES:
                    time.sleep(10)
                else:
                    return None
    return None


# ---------- Gemini backend ----------

_gemini_client = None


def _get_gemini_client():
    global _gemini_client
    if _gemini_client is not None:
        return _gemini_client
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai
    except ImportError:
        print("  [gemini] SDK not installed (pip install google-genai)", flush=True)
        return None
    _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client


def _gemini_generate(prompt: str, model: str, temperature: float):
    client = _get_gemini_client()
    if client is None:
        raise RuntimeError("Gemini backend unavailable (no key or SDK)")
    from google.genai import types

    for attempt in range(MAX_RETRIES + 1):
        try:
            print(f"  [gemini:{model} attempt {attempt + 1}/{MAX_RETRIES + 1}]", end=" ", flush=True)
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=temperature,
                ),
            )
            parsed = _parse_json(resp.text)
            if parsed is None:
                print("JSON parse failed, retrying...", flush=True)
                if attempt < MAX_RETRIES:
                    time.sleep(15)
                    continue
                return None
            print("OK", flush=True)
            return parsed
        except Exception as e:
            kind = _classify_error(e)
            preview = str(e)[:150]
            if kind == "project":
                print(f"\n  FATAL: {preview}", flush=True)
                raise ProjectError(str(e)) from e
            if kind == "model_404":
                print(f"not available", flush=True)
                return None
            if kind == "rate_limit":
                if attempt < MAX_RETRIES:
                    wait = 60 * (attempt + 1)
                    print(f"rate-limited, waiting {wait}s...", flush=True)
                    time.sleep(wait)
                else:
                    print(f"exhausted retries", flush=True)
                    return None
            else:
                print(f"error: {preview}", flush=True)
                if attempt < MAX_RETRIES:
                    time.sleep(15)
                else:
                    return None
    return None


# ---------- Backend dispatch ----------

_BACKEND_DISPATCH = {
    "groq": _groq_generate,
    "gemini": _gemini_generate,
}


# ---------- Public API ----------

def generate_json(
    prompt: str,
    *,
    task: str = "summarize",
    backend: str | None = None,
    temperature: float = 0.3,
):
    """
    Generate a JSON response using the model chain for `task`.

    If `backend` is provided (legacy callers), a flat fallback is used:
    all Groq models then all Gemini models. New callers should use `task`.
    """
    if backend is not None:
        # Legacy path: flat chain through all models in backend order
        chain = _build_legacy_chain(backend)
    else:
        chain = TASK_CHAINS.get(task)
        if chain is None:
            raise ValueError(f"Unknown task: {task}")

    for be, model in chain:
        impl = _BACKEND_DISPATCH.get(be)
        if impl is None:
            continue
        try:
            result = impl(prompt, model, temperature)
        except (ProjectError, QuotaExhausted):
            raise
        except RuntimeError as e:
            print(f"  [{be}] unavailable: {e}", flush=True)
            continue
        if result is not None:
            return result
        print(f"  [{be}:{model}] failed, trying next", flush=True)

    print("  WARNING: All models exhausted, returning None", file=sys.stderr, flush=True)
    return None


def _build_legacy_chain(backend: str) -> list[tuple[str, str]]:
    groq_models = [
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "meta-llama/llama-4-maverick-17b-128e-instruct",
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
    ]
    chain: list[tuple[str, str]] = []
    chain.extend(("groq", m) for m in groq_models)
    chain.extend(("gemini", m) for m in GEMINI_MODELS)
    return chain


def throttle(extra_delay: int = 0):
    total = REQUEST_DELAY + extra_delay
    if total > 0:
        print(f"  [throttle {total}s]", flush=True)
        time.sleep(total)
