"""
Shared Gemini API client — ultra-conservative, slow-and-steady approach.

We have 3 full days (Friday-Sunday) to make ~20 API calls total.
There is zero reason to rush. Generous delays, smart error handling,
and fail-fast on unrecoverable errors.
"""

import json
import os
import re
import sys
import time

from google import genai
from google.genai import types

# Models ordered by free-tier generosity (highest quota first).
# All have Unlimited RPD except the last two.
PREFERRED_MODELS = [
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.5-flash",
]

DEFAULT_DELAY = 30  # seconds between API calls — we have days, not minutes
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
    Classify an API error into one of:
      'project'     — unrecoverable (bad key, spending cap, disabled project)
      'rate_limit'  — temporary, can be retried after waiting
      'model_404'   — model doesn't exist, skip to next model
      'transient'   — unknown/temporary, retry a couple times
    """
    msg = str(e).lower()

    if any(phrase in msg for phrase in [
        "spending cap",
        "api key expired",
        "api_key_invalid",
        "api key not valid",
        "permission denied",
        "project has been deleted",
        "billing",
        "account is inactive",
    ]):
        return "project"

    if "429" in msg or "resource_exhausted" in msg:
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
    """Extract JSON from response, handling markdown fences."""
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
    """
    Call Gemini with conservative retry strategy.

    Priority: gemini-2.0-flash-lite → gemini-2.5-flash-lite → gemini-2.0-flash → gemini-2.5-flash

    Fail-fast on project-level errors (bad key, spending cap).
    Retry with backoff only on genuine rate limits.
    Skip to next model on 404.
    """
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
                    print(f"\n  FATAL: Project-level error — {error_preview}", flush=True)
                    print("  This is unrecoverable. Check your API key and project settings.", flush=True)
                    print("  Ensure the key is from a FREE TIER project with NO billing linked.", flush=True)
                    raise ProjectError(str(e)) from e

                if error_type == "model_404":
                    print(f"model not available, trying next", flush=True)
                    break

                if error_type == "rate_limit":
                    if attempt < MAX_RETRIES:
                        wait = 90 * (attempt + 1)
                        print(f"rate-limited, waiting {wait}s...", flush=True)
                        time.sleep(wait)
                    else:
                        print(f"still rate-limited after {MAX_RETRIES + 1} tries, trying next model", flush=True)
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
    """Sleep between API calls. We have 3 days for ~20 calls. No rush."""
    total = REQUEST_DELAY + extra_delay
    print(f"  [throttle {total}s]", flush=True)
    time.sleep(total)
