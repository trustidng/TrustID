"""List or revoke TrustID signing keys. Rotation uses setup_signing_key.py."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import audit
from app.db import connection, execute, fetch_all, fetch_one


def main() -> None:
    action = sys.argv[1].lower() if len(sys.argv) > 1 else "list"
    with connection() as conn:
        if action == "list":
            for row in fetch_all(conn, "SELECT key_id,algorithm,status,activated_at,retired_at,revoked_at FROM signing_keys ORDER BY created_at DESC"):
                print(row)
            return
        if action != "revoke" or len(sys.argv) != 3:
            raise SystemExit("Usage: manage_signing_keys.py [list | revoke <key-id>]")
        key_id = sys.argv[2]
        key = fetch_one(conn, "SELECT key_id,status FROM signing_keys WHERE key_id=%s FOR UPDATE", (key_id,))
        if not key:
            raise SystemExit("Signing key not found")
        if key["status"] == "ACTIVE":
            raise SystemExit("Rotate to a new active key before revoking the current key")
        execute(conn, "UPDATE signing_keys SET status='REVOKED',revoked_at=UTC_TIMESTAMP() WHERE key_id=%s", (key_id,))
        audit(conn, "SIGNING_KEY_REVOKED", "SYSTEM", None, key_id, None)
        conn.commit()
        print(f"Revoked signing key {key_id}.")


if __name__ == "__main__":
    main()
