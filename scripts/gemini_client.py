"""
Shared Gemini API client with rate limiting, retry, and backoff.
All scripts import this instead of calling the API directly.
"""

import json
import os
import sys
import time
from functools import wraps

from google import genai
from google.genai import types

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
REQUEST_DELAY = int(os.environ.get("GEMINI_DELAY_SECONDS", "15"))
MAX_RETRIES = int(os.environ.get("GEMINI_MAX_RETRIES", "3"))


def create_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)
    return genai.Client(api_key=api_key)


def generate_json(
    client: genai.Client,
    prompt: str,
    *,
    model: str | None = None,
    temperature: float = 0.3,
) -> dict | list | None:
    """
    Call Gemini with rate limiting, retry on 429, and JSON parsing.
    Returns parsed JSON or None on failure.
    """
    model_name = model or DEFAULT_MODEL
    attempt = 0
    backoff = 60

    while attempt <= MAX_RETRIES:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=temperature,
                ),
            )
            result = json.loads(response.text)
            return result
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                attempt += 1
                if attempt > MAX_RETRIES:
                    print(f"  [ERROR] Rate limited after {MAX_RETRIES} retries: {e}", file=sys.stderr)
                    return None
                wait = backoff * attempt
                print(f"  [RATE-LIMITED] Waiting {wait}s before retry {attempt}/{MAX_RETRIES}...")
                time.sleep(wait)
            elif "JSONDecodeError" in error_str or isinstance(e, (json.JSONDecodeError, TypeError)):
                print(f"  [WARN] Failed to parse response as JSON: {e}", file=sys.stderr)
                return None
            else:
                print(f"  [ERROR] Gemini API error: {e}", file=sys.stderr)
                return None

    return None


def throttle():
    """Sleep between API calls to stay under RPM limits."""
    print(f"  [throttle] Waiting {REQUEST_DELAY}s before next request...")
    time.sleep(REQUEST_DELAY)
