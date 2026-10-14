"""
Loads every .txt file in sample_docs/ into the `chunks` table in Supabase.
Uses the SERVICE ROLE key because inserting documents is an admin/ingestion
action, not something a regular logged-in user should be able to do.

Run:  python ingest_docs.py
"""

import os
import glob
from supabase import create_client
from sentence_transformers import SentenceTransformer

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
model = SentenceTransformer("all-MiniLM-L6-v2")  # 384-dim, small, fast on CPU


def parse_doc(path: str) -> dict:
    """Simple front-matter parser: first lines are DEPT/CLASS/TITLE, rest is content."""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    meta = {}
    content_start = 0
    for i, line in enumerate(lines):
        if line.startswith("DEPT:"):
            meta["department"] = line.split(":", 1)[1].strip()
        elif line.startswith("CLASS:"):
            meta["classification"] = line.split(":", 1)[1].strip()
        elif line.startswith("TITLE:"):
            meta["doc_title"] = line.split(":", 1)[1].strip()
        else:
            if line.strip() == "" and meta.get("doc_title"):
                content_start = i + 1
                break

    content = "\n".join(lines[content_start:]).strip()
    meta["content"] = content
    return meta


def chunk_text(text: str, max_chars: int = 400) -> list[str]:
    """Naive paragraph-based chunking -- good enough for a mini project."""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks, current = [], ""
    for p in paragraphs:
        if len(current) + len(p) > max_chars and current:
            chunks.append(current.strip())
            current = ""
        current += p + " "
    if current.strip():
        chunks.append(current.strip())
    return chunks


# 'unassigned' is the no-access default for new users (see schema.sql), so a
# document must never be tagged with it, or every new account could read it.
ALLOWED_DEPARTMENTS = {"hr", "finance", "engineering"}
ALLOWED_CLASSIFICATIONS = {"public", "internal", "restricted"}


def validate_doc(path: str, doc: dict):
    dept, cls = doc.get("department"), doc.get("classification")
    if dept not in ALLOWED_DEPARTMENTS:
        raise SystemExit(f"{path}: DEPT must be one of {sorted(ALLOWED_DEPARTMENTS)}, got {dept!r}")
    if cls not in ALLOWED_CLASSIFICATIONS:
        raise SystemExit(f"{path}: CLASS must be one of {sorted(ALLOWED_CLASSIFICATIONS)}, got {cls!r}")
    if not doc.get("doc_title"):
        raise SystemExit(f"{path}: missing TITLE line")


def main():
    files = sorted(glob.glob("sample_docs/*.txt"))
    print(f"Found {len(files)} documents.")

    rows = []
    for path in files:
        doc = parse_doc(path)
        validate_doc(path, doc)
        for chunk in chunk_text(doc["content"]):
            rows.append({
                "doc_title": doc["doc_title"],
                "content": chunk,
                "department": doc["department"],
                "classification": doc["classification"],
            })

    print(f"Produced {len(rows)} chunks. Embedding...")
    texts = [r["content"] for r in rows]
    embeddings = model.encode(texts, normalize_embeddings=True)

    for row, emb in zip(rows, embeddings):
        row["embedding"] = emb.tolist()

    print("Inserting into Supabase...")
    # clear old data first so re-runs don't duplicate
    supabase.table("chunks").delete().neq("id", 0).execute()
    supabase.table("chunks").insert(rows).execute()

    print(f"Done. Inserted {len(rows)} chunks across {len(files)} documents.")
    for r in rows:
        print(f"  [{r['department']:<12}][{r['classification']:<10}] {r['content'][:60]}...")


if __name__ == "__main__":
    main()
