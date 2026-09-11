"""Database-backed acceptance check for multi-admin governance and oversight."""
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.auth import SESSION_COOKIE, create_session
from app.db import connection, execute, fetch_one
from app.main import app
from app.security import hash_password


def main() -> None:
    suffix = uuid4().hex[:8]
    owner_name = f"acceptance.owner.{suffix}"
    child_name = f"acceptance.admin.{suffix}"
    owner_id = child_id = None
    with connection() as conn:
        try:
            execute(conn, """INSERT INTO admin_users
                (username,role,active,password_hash,must_change_password)
                VALUES (%s,'SUPER_ADMIN',TRUE,%s,FALSE)""", (owner_name, hash_password("Acceptance!234")))
            owner_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
            token, csrf = create_session(conn, "ADMIN", owner_id)
            organisation_id = fetch_one(conn, "SELECT id FROM organisations ORDER BY id LIMIT 1")["id"]
            conn.commit()

            client = TestClient(app)
            client.cookies.set(SESSION_COOKIE, token)
            assert client.get("/admin/administrators").status_code == 200
            history = client.get(f"/admin/organisations/{organisation_id}/verifications")
            assert history.status_code == 200 and "Administrative oversight" in history.text

            created = client.post("/admin/administrators", data={
                "csrf_token": csrf, "username": child_name, "role": "ADMIN",
                "temporary_password": "Acceptance!567", "password_confirm": "Acceptance!567",
            }, follow_redirects=False)
            assert created.status_code == 303
            child = fetch_one(conn, "SELECT id,must_change_password,active,role FROM admin_users WHERE username=%s", (child_name,))
            assert child and child["must_change_password"] and child["active"] and child["role"] == "ADMIN"
            child_id = child["id"]

            deactivated = client.post(f"/admin/administrators/{child_id}/status", data={
                "csrf_token": csrf, "active": "0",
            }, follow_redirects=False)
            assert deactivated.status_code == 303
            conn.rollback()  # End the earlier read snapshot before checking the route's commit.
            assert not fetch_one(conn, "SELECT active FROM admin_users WHERE id=%s", (child_id,))["active"]

            protected = client.post(f"/admin/administrators/{owner_id}/status", data={
                "csrf_token": csrf, "active": "0",
            }, follow_redirects=False)
            assert protected.status_code == 303 and "error=self" in protected.headers["location"]
            print("Admin governance acceptance passed: roles, creation, deactivation, self-protection, oversight and audit.")
        finally:
            ids = tuple(value for value in (child_id, owner_id) if value)
            if ids:
                placeholders = ",".join(["%s"] * len(ids))
                execute(conn, f"DELETE FROM auth_sessions WHERE actor_type='ADMIN' AND actor_id IN ({placeholders})", ids)
                execute(conn, f"DELETE FROM audit_log WHERE actor_type='ADMIN' AND actor_id IN ({placeholders})", ids)
                if child_id:
                    execute(conn, "DELETE FROM admin_users WHERE id=%s", (child_id,))
                if owner_id:
                    execute(conn, "DELETE FROM admin_users WHERE id=%s", (owner_id,))
                conn.commit()


if __name__ == "__main__":
    main()
