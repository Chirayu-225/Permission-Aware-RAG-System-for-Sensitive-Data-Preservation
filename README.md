# Permission-Aware RAG — Mini Project

A RAG system where document retrieval is scoped by the caller's identity at
the database layer (Postgres Row Level Security), not by prompting the LLM
to "please don't share confidential info." Includes a built-in insecure mode
so you can demo the vulnerability and the fix side by side.

## 0. What you need
- A free Supabase account (no card required): https://supabase.com
  Use a **separate Supabase project** for this. The signup trigger in
  `schema.sql` runs on every account created in the project, and
  `profiles` is a common table name. The free plan allows 2 active projects.
- Python 3.10+

## 1. Create the Supabase project
1. New project on supabase.com, pick any name/region, set a DB password (save it).
2. Wait for it to finish provisioning.
3. Go to Project Settings -> API. Copy three values:
   - `Project URL` -> `SUPABASE_URL`
   - `anon public` key -> `SUPABASE_ANON_KEY`
   - `service_role` key -> `SUPABASE_SERVICE_ROLE_KEY` (secret: never expose it to a frontend)

   Use the **legacy JWT keys** (they start with `eyJ`). The pinned
   `supabase==2.9.1` library predates the newer `sb_publishable_` /
   `sb_secret_` key format, so either use the legacy keys or upgrade the library.

## 2. Run the schema
Go to SQL Editor in the Supabase dashboard, paste the contents of `schema.sql`,
and run it. It is safe to re-run. This creates:
- the `profiles` table (user -> department mapping)
- the `chunks` table (your documents, with RLS enabled)
- the `dept-scoped read` policy (the actual security control)
- the `match_chunks` vector search function (runs as the caller, so RLS applies)
- a trigger that creates a profile for each new account, in the
  `unassigned` department, which can read public documents only

## 3. Turn off public sign-ups
In the Supabase dashboard, open the Authentication settings and turn off
new user sign-ups. Demo users are created by an admin script (step 6), so
nobody needs to sign up. Even if sign-ups stay on, new accounts land in
`unassigned` and can't read restricted documents, but there is no reason
to let strangers create accounts.

## 4. Set environment variables
```bash
cd permission-rag
export SUPABASE_URL="https://xxxx.supabase.co"
export SUPABASE_ANON_KEY="eyJ..."
export SUPABASE_SERVICE_ROLE_KEY="eyJ..."
# optional:
export GEMINI_API_KEY="..."            # real LLM answers (otherwise stubbed)
export GEMINI_MODEL="gemini-2.5-flash" # change if this model is retired
export MATCH_COUNT=3                   # chunks retrieved per question
```
(On Windows, use `set` instead of `export`, or put these in a `.env` and load with `python-dotenv`.)

## 5. Install dependencies
```bash
pip install -r requirements.txt
```
First run will download the `all-MiniLM-L6-v2` embedding model (~80MB), fully free/local.

## 6. Create demo users
```bash
python create_users.py
```
Creates 3 users: `hr.user@demo.test`, `finance.user@demo.test`, `eng.user@demo.test`
(password `DemoPass123!` for all, change in the script if you like) and
assigns each one its department.

## 7. Ingest the sample documents
```bash
python ingest_docs.py
```
Chunks and embeds the 12 documents in `sample_docs/` (13 chunks) and inserts
them into Supabase. Each document's `DEPT` must be `hr`, `finance` or
`engineering`, and `CLASS` must be `public`, `internal` or `restricted`;
ingestion stops on anything else (a document tagged `unassigned` would be
readable by every new account).

## 8. Check the access control
```bash
python security_checks.py                  # add --probe-signup to also test sign-up
```
Creates a temporary account, checks that it starts in `unassigned` and sees
no restricted chunks, checks that the engineering user sees no HR or finance
restricted chunks, then deletes the temporary account.

## 9. Run the backend
```bash
uvicorn main:app --port 8000
```
Then open http://localhost:8000 for the demo page.

## 10. Run the leak test
In another terminal:
```bash
python attack_tests.py
```
Logs in as the **engineering** user and sends two sets of questions to both
endpoints:
- **12 attacks:** direct asks, prompt injection, role spoofing, indirect
  injection via a planted instruction in a public doc, and side-channel probes
- **8 benign control questions:** ordinary questions whose answers are in
  public documents

A **context leak** is counted when a retrieved chunk is `restricted` and
belongs to another department. This is checked from each chunk's metadata,
the same rule the RLS policy and the demo page use, so it catches every
restricted document, including ones without a canary string. If
`GEMINI_API_KEY` is set, the script also counts **answer leaks**: canary
secrets that appear in the LLM's answer.

The results table is printed and saved to `results.md`. **Use those measured
numbers in your report**, not estimates. The benign controls matter: if
ordinary questions also leak in insecure mode, that shows the problem is the
missing authorization check, not a clever prompt.

## 11. For the live demo
1. Show `schema.sql`, highlight the `dept-scoped read` policy. This is the
   entire security mechanism, in about 5 lines of SQL.
2. On the demo page, log in as the engineering user, ask "What is the CEO's
   salary?" in insecure mode and show the HR salary chunk coming back.
3. Ask the same question in secure mode with the same user: the HR chunk is
   gone, because RLS filtered it out before it ever reached the LLM.
4. Show `results.md` from step 10: the measured before/after table.
5. Point out the indirect injection doc (`engineering_onboarding.txt`).
   Its planted "ignore previous instructions" line still can't make
   `/query/secure` return HR content: the attack works against the LLM, but
   the LLM was never given the HR content to leak. That's the core argument:
   **enforce authorization at the data layer, not the prompt layer.**

## 12. Tests
Offline (no Supabase, no model download needed):
```bash
python tests/test_llm_key_not_leaked.py   # API key never in the URL or returned text
python tests/test_schema_static.py        # signup default, re-runnable schema, SECURITY INVOKER
python tests/test_leak_rule.py            # the leak rule attack_tests.py uses
```
Against your Supabase project: `python security_checks.py` (step 8).

## 13. Mapping to OWASP Top 10 for LLM Applications (2025)
- **LLM08: Vector and Embedding Weaknesses.** The core of this project:
  without access control in the vector store, retrieval hands any user's
  question the most similar chunks, whoever owns them. RLS enforces
  permissions inside the vector search itself.
- **LLM02: Sensitive Information Disclosure.** The harm being prevented,
  measured as the context-leak rate.
- **LLM01: Prompt Injection.** Direct and indirect injections are in the
  attack set; they fail against the secure endpoint because the restricted
  data is never in the model's context.

## 14. Security fixes in this version
- **API key leak (fixed).** The Gemini key used to be sent in the URL, and a
  failed LLM call returned the error text, URL and key included, to the
  client. The key now goes in the `x-goog-api-key` header and failures return
  only an HTTP status code (`llm.py`, tested by `tests/test_llm_key_not_leaked.py`).
- **Signup default (fixed).** New accounts used to be placed in
  `engineering`, so anyone who could sign up could read engineering's
  restricted documents. They now start in `unassigned`. If you ran the old
  schema, re-run `schema.sql`, then move any account you didn't create on
  purpose back to no access:
  ```sql
  update profiles set department = 'unassigned'
  where email not in ('hr.user@demo.test', 'finance.user@demo.test', 'eng.user@demo.test');
  ```

## 15. Known limitations (worth stating honestly in your report)
- The corpus is small (12 documents, 13 chunks), so treat the leak rates as
  a demonstration of the mechanism, not a benchmark.
- The context-leak check measures what reaches the LLM. With the stubbed LLM,
  nothing is generated, so answer leaks are only measured when
  `GEMINI_API_KEY` is set, and even then only by canary string matching, not
  paraphrase detection.
- RLS prevents query-layer leaks, but not mistakes in who is assigned to
  which department.
- `/query/insecure` returns restricted data to anyone who can reach the
  server. Keep it to local demos and never deploy it.
- The `role` column and the `internal` classification are defined but not
  used by the policy yet.
