"""
Model health checker — validates every model in TASK_CHAINS is reachable
and can produce JSON output. Run standalone or from CI every 15 days.

Exit codes:
  0 — all models healthy
  1 — at least one model permanently unavailable (404/removed)
  2 — transient failures only (503/rate-limit) — warning, not fatal
"""

import json
import os
import sys
import time

PROBE_PROMPT = 'Respond with exactly this JSON: {"status": "ok"}'

CHINESE_PUBLISHERS = {"qwen", "minimax", "zhipu", "deepseek", "baichuan", "01-ai"}


def _check_groq(model: str) -> dict:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return {"model": model, "backend": "groq", "status": "skip", "reason": "no API key"}
    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": PROBE_PROMPT}],
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=50,
        )
        text = resp.choices[0].message.content
        parsed = json.loads(text)
        if parsed.get("status") == "ok":
            return {"model": model, "backend": "groq", "status": "healthy"}
        return {"model": model, "backend": "groq", "status": "warn", "reason": f"unexpected response: {text[:80]}"}
    except Exception as e:
        msg = str(e).lower()
        if "404" in msg or "not found" in msg or "model_not_found" in msg:
            return {"model": model, "backend": "groq", "status": "dead", "reason": str(e)[:200]}
        if "429" in msg or "rate limit" in msg:
            return {"model": model, "backend": "groq", "status": "rate_limited", "reason": str(e)[:200]}
        if "400" in msg and "json" in msg:
            return {"model": model, "backend": "groq", "status": "json_broken", "reason": str(e)[:200]}
        return {"model": model, "backend": "groq", "status": "error", "reason": str(e)[:200]}


def _check_gemini(model: str) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"model": model, "backend": "gemini", "status": "skip", "reason": "no API key"}
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=model,
            contents=PROBE_PROMPT,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0,
                max_output_tokens=100,
            ),
        )
        text = resp.text or ""
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"model": model, "backend": "gemini", "status": "healthy",
                    "reason": f"reachable but JSON malformed: {text[:80]}"}
        if parsed.get("status") == "ok":
            return {"model": model, "backend": "gemini", "status": "healthy"}
        return {"model": model, "backend": "gemini", "status": "healthy",
                "reason": f"reachable, unexpected payload: {text[:80]}"}
    except Exception as e:
        msg = str(e).lower()
        if "404" in msg or "not found" in msg or "not_found" in msg:
            return {"model": model, "backend": "gemini", "status": "dead", "reason": str(e)[:200]}
        if "429" in msg or "503" in msg or "unavailable" in msg or "resource_exhausted" in msg:
            return {"model": model, "backend": "gemini", "status": "rate_limited", "reason": str(e)[:200]}
        return {"model": model, "backend": "gemini", "status": "error", "reason": str(e)[:200]}


def _is_chinese_model(model_id: str) -> bool:
    lower = model_id.lower()
    return any(pub in lower for pub in CHINESE_PUBLISHERS)


def main():
    from llm_client import TASK_CHAINS

    seen: set[tuple[str, str]] = set()
    models_to_check: list[tuple[str, str]] = []
    for chain in TASK_CHAINS.values():
        for backend, model in chain:
            key = (backend, model)
            if key not in seen:
                seen.add(key)
                models_to_check.append(key)

    print(f"Checking {len(models_to_check)} unique models across all task chains\n")

    checkers = {"groq": _check_groq, "gemini": _check_gemini}
    results = []
    dead_count = 0
    warn_count = 0

    for backend, model in models_to_check:
        if _is_chinese_model(model):
            print(f"  SKIP {backend}:{model} — Chinese-origin publisher")
            continue

        checker = checkers.get(backend)
        if not checker:
            print(f"  SKIP {backend}:{model} — unknown backend")
            continue

        result = checker(model)
        results.append(result)

        status = result["status"]
        icon = {"healthy": "OK", "dead": "DEAD", "json_broken": "JSON-BROKEN",
                "rate_limited": "RATE-LIM", "warn": "WARN", "error": "ERROR",
                "skip": "SKIP"}[status]
        reason = f" — {result['reason']}" if "reason" in result else ""
        print(f"  [{icon}] {backend}:{model}{reason}")

        if status == "dead":
            dead_count += 1
        elif status in ("json_broken", "error", "warn"):
            warn_count += 1

        time.sleep(2)

    print(f"\n--- Summary ---")
    print(f"Total checked: {len(results)}")
    print(f"Healthy: {sum(1 for r in results if r['status'] == 'healthy')}")
    print(f"Dead/removed: {dead_count}")
    print(f"Warnings: {warn_count}")
    print(f"Rate-limited: {sum(1 for r in results if r['status'] == 'rate_limited')}")
    print(f"Skipped: {sum(1 for r in results if r['status'] == 'skip')}")

    # Identify which tasks lose all models
    tasks_at_risk = []
    dead_models = {(r["backend"], r["model"]) for r in results if r["status"] == "dead"}
    for task, chain in TASK_CHAINS.items():
        alive = [m for m in chain if (m[0], m[1]) not in dead_models]
        if not alive:
            tasks_at_risk.append(task)
        elif len(alive) < 2:
            print(f"  WARNING: task '{task}' has only 1 surviving model: {alive[0]}")

    if tasks_at_risk:
        print(f"\n  CRITICAL: tasks with ZERO surviving models: {tasks_at_risk}")

    if dead_count > 0:
        print("\nFAIL: dead models found — update TASK_CHAINS in llm_client.py")
        sys.exit(1)
    elif warn_count > 0:
        print("\nWARN: some models had issues (may be transient)")
        sys.exit(2)
    else:
        print("\nAll models healthy.")
        sys.exit(0)


if __name__ == "__main__":
    main()
