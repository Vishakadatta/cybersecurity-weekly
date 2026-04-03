"""
Shared Gemini API client — slow-and-steady, free-tier safe.

We have 3 full days (Friday-Sunday) to process ~20 API calls.
Gemini 2.5 Pro: 150 RPM, 1K RPD, 2M TPM on free tier.
With 20-second delays between calls, we use < 3 RPM. Plenty of headroom.
"""

import json
import os
import re
import sys
import time

from google import genai
from google.genai import types

PREFERRED_MODELS = [
    "gemini-2.5-pro",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
]

DEFAULT_DELAY = 20
REQUEST_DELAY = int(os.environ.get("GEMINI_DELAY_SECONDS", str(DEFAULT_DELAY)))
MAX_RETRIES = int(os.environ.get("GEMINI_MAX_RETRIES", "2"))


class ProjectError(Exception):
    """Unrecoverable project-level error (bad key, spending cap, disabled project)."""


def create_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)
    return genai.Client(api_key=api_key)


def _classify_error(e: Exception) -> str:
    """
    Classify API errors. Google's 429 errors always include generic text
    like "check your plan and billing details" — do NOT treat that as fatal.
    Only truly unrecoverable errors (bad key, spending cap) are 'project'.
    """
    msg = str(e).lower()

    if any(phrase in msg for phrase in [
        "api key expired",
        "api_key_invalid",
        "api key not valid",
        "permission denied",
        "project has been deleted",
        "account is inactive",
    ]):
        return "project"

    if "spending cap" in msg and "429" in msg:
        return "project"

    if "429" in msg or "resource_exhausted" in msg:
        if "limit: 0" in msg:
            return "model_404"
        return "rate_limit"

    if "404" in msg or "not found" in msg:
        return "model_404"

    return "transient"


def _try_generate(client: genai.Client, model: str, prompt: str, temperature: float):
    return client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=temperature,
        ),
    )


def _parse_json(text: str) -> dict | list | None:
    cleaned = text.strip()
    fence = re.match(r"^```(?:json)?\s*\n?(.*?)```\s*$", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def generate_json(
    client: genai.Client,
    prompt: str,
    *,
    temperature: float = 0.3,
) -> dict | list | None:
    env_model = os.environ.get("GEMINI_MODEL", "").strip()
    if env_model:
        models = [env_model] + [m for m in PREFERRED_MODELS if m != env_model]
    else:
        models = list(PREFERRED_MODELS)

    for model in models:
        for attempt in range(MAX_RETRIES + 1):
            try:
                print(f"  [{model} attempt {attempt + 1}/{MAX_RETRIES + 1}]", end=" ", flush=True)
                response = _try_generate(client, model, prompt, temperature)
                result = _parse_json(response.text)
                if result is None:
                    print("JSON parse failed, retrying...", flush=True)
                    if attempt < MAX_RETRIES:
                        time.sleep(15)
                        continue
                    else:
                        print("JSON parse failed after all attempts", flush=True)
                        break
                print("OK", flush=True)
                return result

            except Exception as e:
                error_type = _classify_error(e)
                error_preview = str(e)[:150]

                if error_type == "project":
                    print(f"\n  FATAL: {error_preview}", flush=True)
                    raise ProjectError(str(e)) from e

                if error_type == "model_404":
                    print(f"not available, trying next model", flush=True)
                    break

                if error_type == "rate_limit":
                    if attempt < MAX_RETRIES:
                        wait = 60 * (attempt + 1)
                        print(f"rate-limited, waiting {wait}s...", flush=True)
                        time.sleep(wait)
                    else:
                        print(f"exhausted retries, trying next model", flush=True)
                        time.sleep(30)
                        break
                else:
                    print(f"error: {error_preview}", flush=True)
                    if attempt < MAX_RETRIES:
                        time.sleep(15)
                    else:
                        break

    print("  WARNING: All models exhausted, returning None", file=sys.stderr, flush=True)
    return None


def throttle(extra_delay: int = 0):
    total = REQUEST_DELAY + extra_delay
    print(f"  [throttle {total}s]", flush=True)
    time.sleep(total)
