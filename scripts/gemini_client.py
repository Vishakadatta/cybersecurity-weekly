"""
Shared Gemini API client with model fallback, rate limiting, and retry.
Rotates through free-tier models to maximize available quota.
"""

import json
import os
import sys
import time

from google import genai
from google.genai import types

FALLBACK_MODELS = [
    "gemini-2.0-flash-lite",   # Unlimited RPD, 4K RPM
    "gemini-3.1-flash-lite",   # 150K RPD, 4K RPM
    "gemini-2.5-flash-lite",   # Unlimited RPD, 4K RPM
    "gemini-2.0-flash",        # Unlimited RPD, 2K RPM
    "gemini-3-flash",          # 10K RPD, 1K RPM
    "gemini-2.5-flash",        # 10K RPD, 1K RPM
]

REQUEST_DELAY = int(os.environ.get("GEMINI_DELAY_SECONDS", "15"))
MAX_RETRIES = int(os.environ.get("GEMINI_MAX_RETRIES", "2"))

_current_model_index = 0


def create_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)
    return genai.Client(api_key=api_key)


def _try_generate(client: genai.Client, model: str, prompt: str, temperature: float):
    """Single attempt to generate content with a specific model."""
    return client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=temperature,
        ),
    )


def generate_json(
    client: genai.Client,
    prompt: str,
    *,
    temperature: float = 0.3,
) -> dict | list | None:
    """
    Call Gemini with model fallback and retry on 429 errors.
    Tries each model in the fallback list before giving up.
    """
    global _current_model_index

    models_to_try = FALLBACK_MODELS[_current_model_index:] + FALLBACK_MODELS[:_current_model_index]

    for model in models_to_try:
        for attempt in range(MAX_RETRIES + 1):
            try:
                print(f"  [model={model}, attempt={attempt + 1}]", end=" ")
                response = _try_generate(client, model, prompt, temperature)
                result = json.loads(response.text)
                _current_model_index = FALLBACK_MODELS.index(model)
                print("OK")
                return result

            except Exception as e:
                error_str = str(e)
                is_rate_limit = "429" in error_str or "RESOURCE_EXHAUSTED" in error_str
                is_not_found = "404" in error_str or "not found" in error_str.lower()

                if is_not_found:
                    print(f"model not available, skipping")
                    break

                if is_rate_limit:
                    if attempt < MAX_RETRIES:
                        wait = 60 * (attempt + 1)
                        print(f"rate-limited, waiting {wait}s...")
                        time.sleep(wait)
                    else:
                        print(f"exhausted after {MAX_RETRIES + 1} attempts, trying next model")
                        break
                else:
                    if "JSONDecodeError" in error_str or isinstance(e, (json.JSONDecodeError, TypeError)):
                        print(f"JSON parse error")
                        return None
                    print(f"error: {error_str[:100]}")
                    if attempt < MAX_RETRIES:
                        time.sleep(10)
                    else:
                        break

    print("  [ERROR] All models exhausted", file=sys.stderr)
    return None


def throttle():
    """Sleep between API calls to stay under RPM limits."""
    print(f"  [throttle {REQUEST_DELAY}s]")
    time.sleep(REQUEST_DELAY)
