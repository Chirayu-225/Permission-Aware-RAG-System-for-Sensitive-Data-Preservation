"""
Regression test for the API-key leak: the Gemini key must never appear in
the URL or in any text returned to the client. Runs offline (no network,
no Supabase, no embedding model).  Run: python tests/test_llm_key_not_leaked.py
"""
import os, sys
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
import llm

SECRET = "AIzaTEST-secret-key-do-not-leak-123"
failed = 0


def check(label, cond):
    global failed
    print(f"{'PASS' if cond else 'FAIL'}: {label}")
    failed += 0 if cond else 1


def fake_response(status, json_body=None):
    r = mock.Mock()
    r.ok = 200 <= status < 300
    r.status_code = status
    r.json.return_value = json_body or {}
    r.text = f"error body mentioning {SECRET}"  # even if the server echoed the key, we must not return it
    return r


# 1. The key goes in a header, never in the URL.
with mock.patch.object(llm.requests, "post", return_value=fake_response(200, {
        "candidates": [{"content": {"parts": [{"text": "hello"}]}}]})) as post:
    out = llm.real_llm_answer("prompt", api_key=SECRET)
    url = post.call_args.args[0]
    headers = post.call_args.kwargs.get("headers", {})
    check("successful call returns the model text", out == "hello")
    check("API key is NOT in the request URL", SECRET not in url and "key=" not in url)
    check("API key is sent in the x-goog-api-key header", headers.get("x-goog-api-key") == SECRET)

# 2. An HTTP error returns only the status code.
with mock.patch.object(llm.requests, "post", return_value=fake_response(429)):
    out = llm.real_llm_answer("prompt", api_key=SECRET)
    check("HTTP error message does not contain the key", SECRET not in out)
    check("HTTP error message reports the status code", "429" in out)

# 3. A network exception whose text contains the key is not echoed.
with mock.patch.object(llm.requests, "post",
                       side_effect=requests.ConnectionError(f"failed for url ...?key={SECRET}")):
    out = llm.real_llm_answer("prompt", api_key=SECRET)
    check("network error message does not contain the key", SECRET not in out)

# 4. A malformed success response is handled without crashing.
with mock.patch.object(llm.requests, "post", return_value=fake_response(200, {"unexpected": True})):
    out = llm.real_llm_answer("prompt", api_key=SECRET)
    check("malformed response is handled", "unexpected response" in out and SECRET not in out)

print(f"\n{'ALL PASS' if failed == 0 else f'{failed} FAILED'}")
sys.exit(1 if failed else 0)
