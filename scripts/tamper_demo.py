"""Safe, development-only visual demonstration of signed-result tamper detection.

Usage:
    python scripts/tamper_demo.py create
    python scripts/tamper_demo.py alter
    python scripts/tamper_demo.py status
    python scripts/tamper_demo.py restore
    python scripts/tamper_demo.py cleanup

Only records carrying the exact marker below can be changed or removed.
"""
import json
from pathlib import Path
import secrets
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import utcnow_naive
from app.db import connection, execute, fetch_one
from app.security import hash_password, new_organisation_reference
from app.signing import SIGNED_FIELDS, canonicalize, sign_completed_result, verification_url, verify_receipt


STATE_PATH = Path(__file__).with_name(".tamper_demo_state.json")
DEMO_MARKER = "TRUSTID_PHASE6_TAMPER_DEMO"


def load_state() -> dict:
    if not STATE_PATH.exists():
        raise SystemExit("No tamper demonstration exists. Run: python scripts/tamper_demo.py create")
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("The tamper demonstration state is unreadable. No database record was changed.") from exc


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def guarded_rows(conn, state: dict) -> tuple[dict, dict, dict]:
    org = fetch_one(conn, "SELECT id,intended_use FROM organisations WHERE id=%s", (state["organisation_id"],))
    verification = fetch_one(conn, """SELECT id,public_reference,purpose FROM verifications
        WHERE id=%s AND organisation_id=%s""", (state["verification_id"], state["organisation_id"]))
    receipt = fetch_one(conn, """SELECT * FROM receipts
        WHERE verification_id=%s AND verification_token=%s""",
        (state["verification_id"], state["verification_token"]))
    if (not org or org["intended_use"] != DEMO_MARKER or not verification
            or verification["purpose"] != DEMO_MARKER or not receipt):
        raise SystemExit("Safety check failed. No ordinary TrustID record will be changed.")
    return org, verification, receipt


def create() -> None:
    if STATE_PATH.exists():
        raise SystemExit("A tamper demonstration already exists. Run cleanup before creating another one.")
    suffix = secrets.token_hex(5).upper()
    organisation_id = verification_id = None
    try:
        with connection() as conn:
            category = fetch_one(conn, "SELECT id FROM organisation_categories WHERE active=TRUE ORDER BY id LIMIT 1")
            citizen = fetch_one(conn, "SELECT citizen_id FROM citizens WHERE record_status='ACTIVE' ORDER BY citizen_id LIMIT 1")
            if not category or not citizen:
                raise SystemExit("Create the TrustID seed data before starting the demonstration.")
            execute(conn, """INSERT INTO organisations
                (public_reference,business_name,email,phone,category_id,status,password_hash,intended_use)
                VALUES (%s,%s,%s,%s,%s,'APPROVED',%s,%s)""",
                (new_organisation_reference(), f"TrustID Tamper Demonstration {suffix}",
                 f"tamper-demo-{suffix}@trustid.test", "+2348031888888", category["id"],
                 hash_password(secrets.token_urlsafe(24)), DEMO_MARKER))
            organisation_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
            now = utcnow_naive()
            execute(conn, """INSERT INTO verifications
                (public_reference,organisation_id,citizen_id,subject_authority,source_record_id,subject_reference,claim_code,
                 condition_expression,purpose,policy_decision,policy_reason,result,issued_at,expires_at)
                VALUES (%s,%s,%s,'NATIONAL_ID',%s,%s,'AGE_COMPARE','>= 18',%s,
                'ALLOW_INSTANT','ALLOWED','CONDITION_SATISFIED',%s,DATE_ADD(%s,INTERVAL 24 HOUR))""",
                (f"VR-DEMO-{suffix}", organisation_id, citizen["citizen_id"], citizen["citizen_id"],
                 f"SUB-DEMO-{suffix}", DEMO_MARKER, now, now))
            verification_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
            receipt = sign_completed_result(conn, verification_id)
            conn.commit()
        state = {
            "marker": DEMO_MARKER,
            "organisation_id": organisation_id,
            "verification_id": verification_id,
            "verification_reference": f"VR-DEMO-{suffix}",
            "verification_token": receipt["verification_token"],
            "original_canonical_payload": receipt["canonical_payload"],
            "altered": False,
        }
        save_state(state)
        print("Tamper demonstration created.")
        print("Open this link to see: Authentic and current")
        print(verification_url(receipt["verification_token"]))
    except Exception:
        if organisation_id:
            with connection() as cleanup_conn:
                if verification_id:
                    execute(cleanup_conn, "DELETE FROM receipts WHERE verification_id=%s", (verification_id,))
                    execute(cleanup_conn, "DELETE FROM audit_log WHERE target_reference LIKE 'VR-DEMO-%'")
                    execute(cleanup_conn, "DELETE FROM verifications WHERE id=%s", (verification_id,))
                execute(cleanup_conn, "DELETE FROM organisations WHERE id=%s AND intended_use=%s",
                        (organisation_id, DEMO_MARKER))
                cleanup_conn.commit()
        raise


def alter() -> None:
    state = load_state()
    with connection() as conn:
        _, _, receipt = guarded_rows(conn, state)
        if state.get("altered"):
            raise SystemExit("The disposable receipt is already altered. Open the same link or run restore.")
        if receipt["canonical_payload"] != state["original_canonical_payload"]:
            raise SystemExit("The receipt no longer matches the saved demonstration baseline. No change was made.")
        payload = json.loads(receipt["canonical_payload"])
        payload["condition"] = ">= 21"
        execute(conn, "UPDATE receipts SET canonical_payload=%s WHERE verification_id=%s",
                (canonicalize({field: payload[field] for field in SIGNED_FIELDS}), state["verification_id"]))
        conn.commit()
    state["altered"] = True
    save_state(state)
    print("The disposable signed condition was changed from '>= 18' to '>= 21'.")
    print("Refresh this link to see: Invalid or altered")
    print(verification_url(state["verification_token"]))


def restore() -> None:
    state = load_state()
    with connection() as conn:
        guarded_rows(conn, state)
        execute(conn, "UPDATE receipts SET canonical_payload=%s WHERE verification_id=%s",
                (state["original_canonical_payload"], state["verification_id"]))
        conn.commit()
    state["altered"] = False
    save_state(state)
    print("The disposable receipt was restored.")
    print("Refresh this link to see: Authentic and current")
    print(verification_url(state["verification_token"]))


def status() -> None:
    state = load_state()
    with connection() as conn:
        guarded_rows(conn, state)
        result, _, _ = verify_receipt(conn, state["verification_token"])
    labels = {"CURRENT": "Authentic and current", "EXPIRED": "Authentic but expired",
              "INVALID": "Invalid or altered", "UNAVAILABLE": "Result unavailable"}
    print(f"Current state: {labels[result]}")
    print(verification_url(state["verification_token"]))


def cleanup() -> None:
    state = load_state()
    with connection() as conn:
        guarded_rows(conn, state)
        execute(conn, "DELETE FROM audit_log WHERE target_reference=%s", (state["verification_reference"],))
        execute(conn, "DELETE FROM receipts WHERE verification_id=%s", (state["verification_id"],))
        execute(conn, "DELETE FROM verifications WHERE id=%s", (state["verification_id"],))
        execute(conn, "DELETE FROM organisations WHERE id=%s AND intended_use=%s",
                (state["organisation_id"], DEMO_MARKER))
        conn.commit()
    STATE_PATH.unlink(missing_ok=True)
    print("Tamper demonstration records were removed.")


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"create", "alter", "status", "restore", "cleanup"}:
        raise SystemExit("Usage: python scripts/tamper_demo.py [create|alter|status|restore|cleanup]")
    {"create": create, "alter": alter, "status": status,
     "restore": restore, "cleanup": cleanup}[sys.argv[1]]()


if __name__ == "__main__":
    main()
