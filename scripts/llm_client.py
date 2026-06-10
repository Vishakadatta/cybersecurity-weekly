"""
Provider-agnostic LLM client with fallback chain.

Backends (Western/allied-origin only):
- Groq (Meta Llama 3.3 70B / 3.1 8B) — fast, free, used for summarization
- Gemini 2.5 Pro / Flash — used for judgment-heavy tournament ranking

Backend is selected per-call via the `backend` argument. Each backend has its
own internal model fallback chain. If a whole backend is exhausted, the next
fallback backend in `BACKEND_FALLBACKS` is tried.
"""

import json
import os
import re
import sys
import time

# Groq fallback chain. Llama 4 Scout is the head of the chain by default
# because Llama 4 Maverick (the larger 400B MoE) has been intermittently
# returning model_404 on Groq's production API for some accounts. Keeping
# Maverick first wasted ~500ms per LLM call retrying a known-failing model
# before the chain reached Scout. Scout (17B active / 109B total MoE) is
# still a Llama 4, just with fewer experts — quality is very close for
# this workload (summarization + 1-10 relevance scoring).
#
# To restore Maverick as primary (e.g. if your Groq account regains access,
# or if it's working on a future paid tier), set:
#     GROQ_PRIMARY_MODEL=meta-llama/llama-4-maverick-17b-128e-instruct
PREFERRED_GROQ_MODELS = [
    "meta-llama/llama-4-scout-17b-16e-instruct",        # 109B total MoE — primary (proven available)
    "meta-llama/llama-4-maverick-17b-128e-instruct",    # 400B total MoE — try if Scout is down
    "llama-3.3-70b-versatile",                          # 70B dense — safety net
    "llama-3.1-8b-instant",                             # 8B dense — last resort within Groq
]

PREFERRED_GEMINI_MODELS = [
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]

# Per user policy: Gemini is the absolute last resort. The Groq backend
# must exhaust every model in its chain before any Gemini call is made.
# Both "groq" and "gemini" entry points use the same order.
BACKEND_FALLBACKS = {
    "groq": ["groq", "gemini"],
    "gemini": ["groq", "gemini"],
}

DEFAULT_DELAY = 5
REQUEST_DELAY = int(os.environ.get("LLM_DELAY_SECONDS", str(DEFAULT_DELAY)))
MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "2"))


class ProjectError(Exception):
    """Unrecoverable error (bad key, banned project, spending cap)."""


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


def _groq_generate(prompt: str, temperature: float):
    client = _get_groq_client()
    if client is None:
        raise RuntimeError("Groq backend unavailable (no key or SDK)")

    env_model = os.environ.get("GROQ_PRIMARY_MODEL", os.environ.get("GROQ_MODEL", "")).strip()
    models = [env_model] + [m for m in PREFERRED_GROQ_MODELS if m != env_model] if env_model else list(PREFERRED_GROQ_MODELS)

    for model in models:
        for attempt in range(MAX_RETRIES + 1):
            try:
                print(f"  [groq:{model} attempt {attempt + 1}/{MAX_RETRIES + 1}]", end=" ", flush=True)
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                    response_format={"type": "json_object"},
                )
                text = resp.choices[0].message.content
                parsed = _parse_json(text)
                if parsed is None:
                    print("JSON parse failed, retrying...", flush=True)
                    if attempt < MAX_RETRIES:
                        time.sleep(10)
                        continue
                    break
                print("OK", flush=True)
                return parsed
            except Exception as e:
                kind = _classify_error(e)
                preview = str(e)[:150]
                if kind == "project":
                    print(f"\n  FATAL: {preview}", flush=True)
                    raise ProjectError(str(e)) from e
                if kind == "model_404":
                    print(f"not available, trying next model", flush=True)
                    break
                if kind == "rate_limit":
                    if attempt < MAX_RETRIES:
                        wait = 30 * (attempt + 1)
                        print(f"rate-limited, waiting {wait}s...", flush=True)
                        time.sleep(wait)
                    else:
                        print(f"exhausted retries", flush=True)
                        break
                else:
                    print(f"error: {preview}", flush=True)
                    if attempt < MAX_RETRIES:
                        time.sleep(10)
                    else:
                        break
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


def _gemini_generate(prompt: str, temperature: float):
    client = _get_gemini_client()
    if client is None:
        raise RuntimeError("Gemini backend unavailable (no key or SDK)")
    from google.genai import types

    env_model = os.environ.get("GEMINI_MODEL", "").strip()
    models = [env_model] + [m for m in PREFERRED_GEMINI_MODELS if m != env_model] if env_model else list(PREFERRED_GEMINI_MODELS)

    for model in models:
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
                    break
                print("OK", flush=True)
                return parsed
            except Exception as e:
                kind = _classify_error(e)
                preview = str(e)[:150]
                if kind == "project":
                    print(f"\n  FATAL: {preview}", flush=True)
                    raise ProjectError(str(e)) from e
                if kind == "model_404":
                    print(f"not available, trying next model", flush=True)
                    break
                if kind == "rate_limit":
                    if attempt < MAX_RETRIES:
                        wait = 60 * (attempt + 1)
                        print(f"rate-limited, waiting {wait}s...", flush=True)
                        time.sleep(wait)
                    else:
                        print(f"exhausted retries", flush=True)
                        break
                else:
                    print(f"error: {preview}", flush=True)
                    if attempt < MAX_RETRIES:
                        time.sleep(15)
                    else:
                        break
    return None


# ---------- Public API ----------

_BACKEND_IMPL = {
    "groq": _groq_generate,
    "gemini": _gemini_generate,
}


def generate_json(prompt: str, *, backend: str = "groq", temperature: float = 0.3):
    """
    Generate a JSON response. `backend` picks the primary backend; the
    BACKEND_FALLBACKS chain is tried in order if the primary fails.
    """
    chain = BACKEND_FALLBACKS.get(backend, [backend])
    for be in chain:
        impl = _BACKEND_IMPL.get(be)
        if impl is None:
            continue
        try:
            result = impl(prompt, temperature)
        except ProjectError:
            raise
        except RuntimeError as e:
            print(f"  [{be}] unavailable: {e}", flush=True)
            continue
        if result is not None:
            return result
        print(f"  [{be}] exhausted, falling through to next backend", flush=True)
    print("  WARNING: All backends exhausted, returning None", file=sys.stderr, flush=True)
    return None


def throttle(extra_delay: int = 0):
    total = REQUEST_DELAY + extra_delay
    if total > 0:
        print(f"  [throttle {total}s]", flush=True)
        time.sleep(total)
