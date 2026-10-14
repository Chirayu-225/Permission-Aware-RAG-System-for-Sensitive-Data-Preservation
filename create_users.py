"""
Creates 3 demo users, one per department, and fixes their `department`
field in the profiles table (the signup trigger sets a placeholder).

Run:  python create_users.py
"""

import os
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

DEMO_USERS = [
    {"email": "hr.user@demo.test",     "password": "DemoPass123!", "department": "hr"},
    {"email": "finance.user@demo.test","password": "DemoPass123!", "department": "finance"},
    {"email": "eng.user@demo.test",    "password": "DemoPass123!", "department": "engineering"},
]


def main():
    for u in DEMO_USERS:
        try:
            result = supabase.auth.admin.create_user({
                "email": u["email"],
                "password": u["password"],
                "email_confirm": True,
            })
            user_id = result.user.id
            print(f"Created {u['email']} -> {user_id}")
        except Exception as e:
            print(f"Skipping {u['email']} (likely already exists): {e}")
            # fetch existing user id instead
            users = supabase.auth.admin.list_users()
            match = next((x for x in users if x.email == u["email"]), None)
            if not match:
                continue
            user_id = match.id

        # fix department (overwrite the placeholder from the signup trigger)
        supabase.table("profiles").update({"department": u["department"]}).eq("id", user_id).execute()
        print(f"  -> department set to {u['department']}")

    print("\nDemo users ready:")
    for u in DEMO_USERS:
        print(f"  {u['email']} / {u['password']}  (dept: {u['department']})")


if __name__ == "__main__":
    main()
