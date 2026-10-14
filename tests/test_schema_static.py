"""
Static checks on schema.sql for the signup-default fix and re-runnability.
Runs offline.  Run: python tests/test_schema_static.py
(The live behaviour is checked by security_checks.py against Supabase.)
"""
import os, re, sys

SCHEMA = open(os.path.join(os.path.dirname(__file__), "..", "schema.sql"), encoding="utf-8").read()
failed = 0


def check(label, cond):
    global failed
    print(f"{'PASS' if cond else 'FAIL'}: {label}")
    failed += 0 if cond else 1


trigger = SCHEMA[SCHEMA.index("create or replace function handle_new_user()"):]
trigger = trigger[:trigger.index("$$;") + 3]
check("signup trigger assigns 'unassigned'", "'unassigned'" in trigger)
check("signup trigger does not assign a real department",
      not re.search(r"'(engineering|hr|finance)'", trigger))

for name in re.findall(r'create policy "([^"]+)"', SCHEMA):
    check(f'policy "{name}" is dropped first, so the schema can be re-run',
          f'drop policy if exists "{name}"' in SCHEMA)

match_fn = SCHEMA[SCHEMA.index("create or replace function match_chunks"):]
match_fn = match_fn[:match_fn.index("$$;") + 3]
check("match_chunks is not SECURITY DEFINER (RLS must apply inside it)",
      "security definer" not in match_fn.lower())

print(f"\n{'ALL PASS' if failed == 0 else f'{failed} FAILED'}")
sys.exit(1 if failed else 0)
