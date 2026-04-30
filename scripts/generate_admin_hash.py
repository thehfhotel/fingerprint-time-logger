#!/usr/bin/env python3
"""
Generate a bcrypt hash for the admin passcode.

Usage:
  Inside the running container (preferred — uses the same bcrypt version
  as the app):
    docker exec fingerprint-time-logger python scripts/generate_admin_hash.py

  From the host (requires `pip install bcrypt`):
    python3 scripts/generate_admin_hash.py

The script will prompt for the passcode (input is hidden) and print only
the bcrypt hash. Add the hash to your .env as ADMIN_PASSCODE_HASH and
restart the container.

Never commit the plaintext passcode anywhere — only the bcrypt hash.
"""
import getpass
import sys

import bcrypt


def main() -> int:
    passcode = getpass.getpass("Admin passcode: ")
    confirm = getpass.getpass("Confirm passcode: ")
    if passcode != confirm:
        print("Passcodes do not match.", file=sys.stderr)
        return 1
    if len(passcode) < 12:
        print("Passcode must be at least 12 characters.", file=sys.stderr)
        return 1

    hashed = bcrypt.hashpw(passcode.encode("utf-8"), bcrypt.gensalt(rounds=12))
    print(hashed.decode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
