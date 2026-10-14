"""
Permission-Aware RAG backend.

Two query endpoints on purpose, for the demo:

  /login           -> exchanges email+password for a Supabase user JWT
  /query/secure    -> runs retrieval AS THE LOGGED-IN USER (RLS enforced)
  /query/insecure  -> runs retrieval with the service_role key (RLS bypassed)

The insecure endpoint exists ONLY to prove the vulnerability in your demo.
Delete it (or gate it behind a flag) once you've shown the before/after.

Run:  uvicorn main:app --reload --port 8000
"""

import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from supabase import create_client
from sentence_transformers import SentenceTransformer

from llm import get_answer

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

# How many chunks to retrieve per question. Kept small so retrieval has to
# choose; with a tiny corpus and a large k, every query returns nearly the
# whole table and the attack wording stops mattering.
MATCH_COUNT = int(os.environ.get("MATCH_COUNT", "3"))

app = FastAPI(title="Permission-Aware RAG Demo")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

model = SentenceTransformer("all-MiniLM-L6-v2")


class LoginRequest(BaseModel):
    email: str
    password: str


class QueryRequest(BaseModel):
    question: str
    access_token: str | None = None  # required for /query/secure


def embed(text: str) -> list[float]:
    return model.encode([text], normalize_embeddings=True)[0].tolist()


def build_prompt(question: str, chunks: list[dict]) -> str:
    context = "\n\n".join(f"[{c['doc_title']}] {c['content']}" for c in chunks)
    return (
        "Answer the user's question using ONLY the context below. "
        "If the context does not contain the answer, say you don't know.\n\n"
        f"CONTEXT:\n{context}\n\nQUESTION: {question}\nANSWER:"
    )


@app.post("/login")
def login(req: LoginRequest):
    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    try:
        result = client.auth.sign_in_with_password({"email": req.email, "password": req.password})
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))
    return {
        "access_token": result.session.access_token,
        "user_id": result.user.id,
        "email": result.user.email,
    }


@app.post("/query/secure")
def query_secure(req: QueryRequest):
    """RLS-enforced retrieval: runs as the logged-in user. This is the FIX."""
    if not req.access_token:
        raise HTTPException(status_code=401, detail="access_token required")

    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    # Critical line: attach the user's own JWT so every query below
    # runs AS THAT USER, which means RLS policies apply.
    client.postgrest.auth(req.access_token)

    query_embedding = embed(req.question)
    result = client.rpc("match_chunks", {
        "query_embedding": query_embedding,
        "match_count": MATCH_COUNT,
    }).execute()

    chunks = result.data
    prompt = build_prompt(req.question, chunks)
    return {
        "mode": "secure",
        "chunks_retrieved": chunks,
        "answer": get_answer(prompt),
    }


@app.post("/query/insecure")
def query_insecure(req: QueryRequest):
    """
    VULNERABLE retrieval: uses the service_role key, which bypasses RLS
    entirely. This is what happens when a backend queries Supabase with
    the admin key instead of forwarding the user's own token -- a real,
    common mistake. Kept here only to demonstrate the leak in your demo.
    """
    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    query_embedding = embed(req.question)
    result = client.rpc("match_chunks", {
        "query_embedding": query_embedding,
        "match_count": MATCH_COUNT,
    }).execute()

    chunks = result.data
    prompt = build_prompt(req.question, chunks)
    return {
        "mode": "insecure (service_role, RLS bypassed)",
        "chunks_retrieved": chunks,
        "answer": get_answer(prompt),
    }


@app.get("/health")
def health():
    # match_count is reported so attack_tests.py can record the exact
    # retrieval setting alongside its results.
    return {"status": "ok", "match_count": MATCH_COUNT}


# Serves the demo frontend from the SAME server as the API.
# This means no separate file to open, no cross-origin calls --
# just one process, one URL: http://localhost:8000
FRONTEND_PATH = Path(__file__).parent / "demo.html"


@app.get("/")
def serve_frontend():
    return FileResponse(FRONTEND_PATH)
