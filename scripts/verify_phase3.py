"""Read-only Phase 3 acceptance checks against the configured MySQL database."""
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import connection, fetch_one
from app.verification import Condition, ResultCode, VerificationEngine
from app.verification.pseudonyms import subject_reference


def satisfied(result) -> bool:
    return result.result == ResultCode.CONDITION_SATISFIED


def main() -> None:
    today = datetime.now(timezone.utc).date()
    with connection() as conn:
        eighteen = fetch_one(conn, "SELECT synthetic_nin FROM citizens WHERE citizen_id=1")
        thirty = fetch_one(conn, "SELECT synthetic_nin FROM citizens WHERE citizen_id=2")
        valid_licence = fetch_one(conn, """SELECT licence_number FROM licences
            WHERE licence_status='VALID' AND issue_date<=%s AND expiry_date>=%s LIMIT 1""", (today, today))
    if not eighteen or not thirty or not valid_licence:
        raise AssertionError("Phase 3 acceptance records are missing; restore the seeded dataset")

    engine = VerificationEngine()
    cases = [
        (eighteen["synthetic_nin"], Condition(">=", 18), True),
        (eighteen["synthetic_nin"], Condition(">", 18), False),
        (eighteen["synthetic_nin"], Condition("BETWEEN", 18, 30), True),
        (thirty["synthetic_nin"], Condition("<=", 30), True),
        (thirty["synthetic_nin"], Condition("<", 30), False),
        (thirty["synthetic_nin"], Condition("BETWEEN", 18, 30), True),
    ]
    for identifier, condition, expected in cases:
        result = engine.evaluate("AGE_COMPARE", identifier, condition, as_of=today)
        if satisfied(result) is not expected:
            raise AssertionError(f"Age boundary failed for {result.normalized_condition}")
        safe_text = repr(result.verifier_safe())
        if identifier in safe_text or "citizen_id" in safe_text or "date_of_birth" in safe_text:
            raise AssertionError("A private identity value crossed the verifier-safe boundary")

    licence_result = engine.evaluate("LICENCE_STATUS", valid_licence["licence_number"], Condition("IS_VALID"), as_of=today)
    if not satisfied(licence_result) or valid_licence["licence_number"] in repr(licence_result.verifier_safe()):
        raise AssertionError("Licence verification failed its privacy-safe acceptance check")

    first = subject_reference(1, licence_result.source_record_id, authority="DRIVING_LICENCE")
    if first == subject_reference(2, licence_result.source_record_id, authority="DRIVING_LICENCE"):
        raise AssertionError("Subject references are not organisation-scoped")

    print("Phase 3 acceptance test passed: adapters, flexible predicates, boundary ages, licence validity, pseudonyms and privacy-safe results.")


if __name__ == "__main__":
    main()
