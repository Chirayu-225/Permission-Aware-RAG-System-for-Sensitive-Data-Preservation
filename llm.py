"""
LLM answer generation, kept in its own small module so it can be tested
without loading the embedding model or connecting to Supabase.

SECURITY FIX: the Gemini API key used to travel in the URL
(`...generateContent?key=...`). When a call failed, `requests` built an
error message containing that full URL, and the error text was returned to
the client in the `answer` field, so any failed call (quota, bad request,
retired model) handed the API key to whoever asked the question.

Now the key goes in the `x-goog-api-key` header, which never appears in the
URL or in requests' error messages, and failures return a generic message
with only the HTTP status code.
"""

import os
import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
# Model names get retired; keep it configurable instead of hardcoded.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def fake_llm_answer(prompt: str) -> str:
    """Stub used only when GEMINI_API_KEY isn't set."""
    return "[No GEMINI_API_KEY set -- answers are stubbed. See README to enable real answers.]"


def real_llm_answer(prompt: str, api_key: str = None) -> str:
    """Calls Gemini. Never puts the key in the URL, and never returns
    exception text (which can carry request details) to the caller."""
    key = api_key or GEMINI_API_KEY
    url = _GEMINI_URL.format(model=GEMINI_MODEL)
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        resp = requests.post(
            url,
            json=payload,
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            timeout=15,
        )
    except requests.RequestException:
        return "[LLM call failed: network error]"

    if not resp.ok:
        # Status code only. The response body and URL are deliberately not
        # echoed back to the client.
        return f"[LLM call failed: HTTP {resp.status_code}]"

    try:
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (ValueError, KeyError, IndexError, TypeError):
        return "[LLM call failed: unexpected response format]"


def get_answer(prompt: str) -> str:
    if GEMINI_API_KEY:
        return real_llm_answer(prompt)
    return fake_llm_answer(prompt)
