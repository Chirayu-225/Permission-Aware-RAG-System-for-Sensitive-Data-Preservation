"""
End-to-end security checks against YOUR Supabase project. Run this after
re-running schema.sql, creating the demo users, and ingesting the documents.

  python security_checks.py                 # access-control checks
  python security_checks.py --probe-signup  # also test whether public sign-up is open

Checks:
  1. A brand-new account starts in the 'unassigned' department (the fixed
     signup trigger), not 'engineering'.
  2. That new account can read ZERO restricted chunks.
  3. The engineering demo user can read no restricted chunks from HR or
     finance, and can read its own department's restricted chunks.
  4. (opt-in) Whether anyone can sign up with just the public anon key. This
     is opt-in because a sign-up attempt may make Supabase send an email to a
     made-up address, and the free plan rate-limits auth emails.

The temporary account is always deleted at the end.
"""

import os
import sys
import uuid

from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

ENG_EMAIL, ENG_PASSWORD = "eng.user@demo.test", "DemoPass123!"
results = []


def check(name, passed, detail=""):
    results.append(passed)
    print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def chunks_visible_to(email, password):
    """Logs in as the user and reads the chunks table AS THAT USER, so RLS applies."""
    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    session = client.auth.sign_in_with_password({"email": email, "password": password}).session
    client.postgrest.auth(session.access_token)
    return client.table("chunks").select("doc_title, department, classification").execute().data


def main():
    admin = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    temp_email = f"secheck-{uuid.uuid4().hex[:8]}@demo.test"
    temp_password = f"Tmp-{uuid.uuid4().hex}"
    temp_id = None

    try:
        temp_id = admin.auth.admin.create_user(
            {"email": temp_email, "password": temp_password, "email_confirm": True}
        ).user.id

        prof = admin.table("profiles").select("department").eq("id", temp_id).execute().data
        dept = prof[0]["department"] if prof else None
        check("New account starts in 'unassigned'", dept == "unassigned", f"got {dept!r}")

        rows = chunks_visible_to(temp_email, temp_password)
        restricted = [r for r in rows if r["classification"] != "public"]
        check("New account sees no restricted chunks", not restricted,
              f"{len(rows)} visible, {len(restricted)} non-public")

        rows = chunks_visible_to(ENG_EMAIL, ENG_PASSWORD)
        foreign = [r for r in rows if r["classification"] == "restricted" and r["department"] != "engineering"]
        own = [r for r in rows if r["classification"] == "restricted" and r["department"] == "engineering"]
        check("Engineering user sees no HR/finance restricted chunks", not foreign,
              ", ".join(sorted({r['doc_title'] for r in foreign})) or "none")
        check("Engineering user can still see its own restricted chunks", bool(own),
              f"{len(own)} visible")

        if "--probe-signup" in sys.argv:
            probe_email = f"signup-probe-{uuid.uuid4().hex[:8]}@demo.test"
            anon = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
            try:
                resp = anon.auth.sign_up({"email": probe_email, "password": f"Tmp-{uuid.uuid4().hex}"})
                opened = resp.user is not None
                if opened:
                    admin.auth.admin.delete_user(resp.user.id)
            except Exception:
                opened = False
            check("Public sign-up is disabled", not opened,
                  "anyone can create an account; turn off sign-ups in Supabase Auth settings" if opened else "sign-up rejected")
        else:
            print("[SKIP] Public sign-up probe (run with --probe-signup to test it)")
    finally:
        if temp_id:
            admin.auth.admin.delete_user(temp_id)

    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
