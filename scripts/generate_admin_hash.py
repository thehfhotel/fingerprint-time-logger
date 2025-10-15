#!/usr/bin/env python3
"""
Generate bcrypt hash for admin passcode
This script is meant to be run once to generate the hash for storage in environment variables
"""
import bcrypt

# Admin passcode as provided by user
passcode = 'H]sN4@Wa3wA9Fg9%<^2^VtJ^mWLDQ9!"j>Eptf,'

# Generate bcrypt hash with cost factor 12 (default)
hashed = bcrypt.hashpw(passcode.encode('utf-8'), bcrypt.gensalt())

print("=" * 80)
print("Admin Passcode Hash Generated")
print("=" * 80)
print("\nAdd this to your .env file:")
print(f"\nADMIN_PASSCODE_HASH={hashed.decode('utf-8')}")
print("\nOriginal passcode (for reference only - DO NOT STORE IN CODE):")
print(f"{passcode}")
print("\n" + "=" * 80)
print("SECURITY NOTES:")
print("- Store the hash in .env file (never commit to version control)")
print("- Add .env to .gitignore")
print("- Delete this script after first use for maximum security")
print("=" * 80)
