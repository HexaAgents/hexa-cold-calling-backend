"""Seed the 5 Hexa user accounts into Supabase Auth.

Usage:
    export SUPABASE_URL="https://gtlvffaqwbxeczmbrhkc.supabase.co"
    export SUPABASE_SERVICE_ROLE_KEY="your-service-role-key"
    python scripts/seed_users.py
"""

import os
import sys

from supabase import create_client, Client

USERS = [
    {"email": "mann@hexaagents.com", "password": "Hexa123", "name": "Mann Patira"},
    {"email": "srijan@hexaagents.com", "password": "Hexa123", "name": "Srijan Tyagi"},
    {"email": "aurideep@hexaagents.com", "password": "Hexa123", "name": "Aurideep Nayak"},
    {"email": "ishaan@hexaagents.com", "password": "Hexa123", "name": "Ishaan Makkar"},
    {"email": "sanuka@hexaagent.com", "password": "Hexa123", "name": "Sanuka Gunawardena"},
]


def main() -> None:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        print("Error: Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY env vars.", file=sys.stderr)
        sys.exit(1)

    client: Client = create_client(url, key)

    for user in USERS:
        try:
            result = client.auth.admin.create_user({
                "email": user["email"],
                "password": user["password"],
                "email_confirm": True,
                "user_metadata": {"full_name": user["name"]},
            })
            print(f"Created: {user['name']} ({user['email']}) — ID: {result.user.id}")
        except Exception as exc:
            if "already been registered" in str(exc).lower() or "already exists" in str(exc).lower():
                print(f"Already exists: {user['name']} ({user['email']})")
            else:
                print(f"Error creating {user['email']}: {exc}", file=sys.stderr)

    print("\nDone. All users seeded.")


if __name__ == "__main__":
    main()
