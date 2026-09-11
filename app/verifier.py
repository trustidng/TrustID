"""Phase 5 verifier workflow helpers and privacy boundaries."""
from dataclasses import dataclass
from datetime import timedelta
import re

import mysql.connector

from .auth import audit, utcnow_naive
from .abuse import BLOCK_MESSAGE, acquire_age_guard, finalize_age_attempt, reserve_age_attempt
from .db import execute, fetch_one
from .policy import PolicyDecisionCode, PolicyEngine
from .security import digest_token, mask_phone, new_token
from .resilience import is_available, record_unavailable
from .signing import sign_completed_result
from .verification import ClaimCode, Condition, VerificationEngine
from .verification.catalog import CLAIM_CATALOG, condition_label
from .verification.errors import InvalidVerificationRequest, TrustedSourceUnavailable
from .verification.pseudonyms import subject_reference, unconfirmed_subject_reference
from .consent import encrypt_request_context


CONSENT_TTL = timedelta(hours=24)
TTL_BY_CLASS = {"SHORT": timedelta(hours=24), "MEDIUM": timedelta(days=30)}
NIGERIAN_STATES = (
    "Abia", "Adamawa", "Akwa Ibom", "Anambra", "Bauchi", "Bayelsa", "Benue", "Borno",
    "Cross River", "Delta", "Ebonyi", "Edo", "Ekiti", "Enugu", "FCT - Abuja", "Gombe",
    "Imo", "Jigawa", "Kaduna", "Kano", "Katsina", "Kebbi", "Kogi", "Kwara", "Lagos",
    "Nasarawa", "Niger", "Ogun", "Ondo", "Osun", "Oyo", "Plateau", "Rivers", "Sokoto",
    "Taraba", "Yobe", "Zamfara",
)
IDENTITY_CLAIMS = {ClaimCode.AGE_COMPARE, ClaimCode.IDENTITY_STATUS,
                   ClaimCode.FULL_LEGAL_NAME, ClaimCode.STATE_OF_ORIGIN,
                   ClaimCode.RESIDENTIAL_ADDRESS, ClaimCode.REGISTERED_RESIDENCE}
CONSENT_CLAIMS = {ClaimCode.FULL_LEGAL_NAME, ClaimCode.STATE_OF_ORIGIN,
                  ClaimCode.RESIDENTIAL_ADDRESS, ClaimCode.REGISTERED_RESIDENCE}
DISCLOSURE_CLAIMS = {ClaimCode.FULL_LEGAL_NAME, ClaimCode.STATE_OF_ORIGIN,
                     ClaimCode.RESIDENTIAL_ADDRESS}
ADMIN_FAILURE_REASONS = {
    "NO_MATCHING_IDENTITY_RECORD": "No matching record was found in the national identity source.",
    "IDENTITY_RECORD_INACTIVE": "The national identity source marked the record as inactive.",
    "IDENTITY_RECORD_REVOKED": "The national identity source marked the record as revoked.",
    "NO_MATCHING_LICENCE_RECORD": "No matching record was found in the driving licence source.",
}
SAFE_PURPOSE_RE = re.compile(r"^[\w\s.,'’&()/\-]{10,180}$", re.UNICODE)
IDENTIFIER_IN_PURPOSE_RE = re.compile(r"(?:\+?234|0)\d{10}|\b\d{10,11}\b|\bLIC[-\s]?\d{6,}\b", re.I)


@dataclass(frozen=True)
class PreparedRequest:
    claim: ClaimCode
    identifier: str
    condition: Condition
    normalized_condition: str
    requirement: str
    purpose: str


def validate_purpose(value: str) -> str:
    purpose = " ".join(value.split())
    if not SAFE_PURPOSE_RE.fullmatch(purpose) or IDENTIFIER_IN_PURPOSE_RE.search(purpose):
        raise ValueError("Enter a clear purpose without personal identifiers.")
    return purpose


def _valid_name_component(value: str, *, optional: bool = False) -> bool:
    if not value:
        return optional
    return 1 <= len(value) <= 100 and all(char.isalpha() or char in " -'’" for char in value)


def condition_from_form(claim: ClaimCode, operator: str, low: str = "", high: str = "", classes: tuple[str, ...] = ()) -> Condition:
    op = operator.strip().upper()
    if claim == ClaimCode.AGE_COMPARE:
        aliases = {"MINIMUM": ">=", "MAXIMUM": "<=", "EXACT": "EXACT", "RANGE": "BETWEEN"}
        op = aliases.get(op, op)
        if op == "EXACT":
            # Equality is represented as an inclusive single-value range.
            op, high = "BETWEEN", low
        return Condition(op, low, high if op == "BETWEEN" else None)
    if claim == ClaimCode.IDENTITY_STATUS:
        return Condition("RECORD_CONFIRMED")
    if claim == ClaimCode.LICENCE_STATUS:
        return Condition(op)
    if claim == ClaimCode.LICENCE_CLASS:
        return Condition("IN_SET", allowed_values=classes) if op == "IN_SET" else Condition("EQUALS", low)
    if claim == ClaimCode.NAME_MATCH:
        return Condition("NAME_MATCH", allowed_values=classes)
    if claim == ClaimCode.REGISTERED_RESIDENCE:
        return Condition("REGISTERED_RESIDENCE_MATCH", allowed_values=classes)
    if claim in CONSENT_CLAIMS:
        return Condition("DISCLOSE_WITH_CONSENT")
    raise ValueError("Choose an available verification.")


def prepare_request(claim_code: str, identifier: str, operator: str, low: str, high: str,
                    classes: tuple[str, ...], purpose: str, *, surname: str = "",
                    first_name: str = "", middle_name: str = "",
                    residence_state: str = "", residence_lga: str = "") -> PreparedRequest:
    try:
        claim = ClaimCode(claim_code)
    except ValueError:
        raise ValueError("Choose an available verification.") from None
    clean_identifier = identifier.strip().upper()
    if claim == ClaimCode.NAME_MATCH:
        if not (re.fullmatch(r"\d{11}", clean_identifier) or re.fullmatch(r"LIC-\d{9}", clean_identifier)):
            raise ValueError("Enter a valid NIN or driving licence number.")
    elif claim in IDENTITY_CLAIMS:
        if not re.fullmatch(r"\d{11}", clean_identifier):
            raise ValueError("Enter a valid registered NIN.")
    elif not re.fullmatch(r"LIC-\d{9}", clean_identifier):
        raise ValueError("Enter a valid driving licence number.")
    clean_purpose = validate_purpose(purpose)
    if claim == ClaimCode.NAME_MATCH:
        parts = tuple(" ".join(value.split()) for value in (surname, first_name, middle_name))
        if (not _valid_name_component(parts[0]) or not _valid_name_component(parts[1])
                or not _valid_name_component(parts[2], optional=True)):
            raise ValueError("Enter the surname and first name exactly as provided by the applicant.")
        condition = condition_from_form(claim, "NAME_MATCH", classes=parts)
    elif claim == ClaimCode.REGISTERED_RESIDENCE:
        location = tuple(" ".join(value.split()) for value in (residence_state, residence_lga))
        state_lookup = {value.casefold(): value for value in NIGERIAN_STATES}
        canonical_state = state_lookup.get(location[0].casefold())
        valid_lga = (not location[1] or len(location[1]) <= 80 and
                     all(char.isalpha() or char in " -'’" for char in location[1]))
        if not canonical_state or not valid_lga:
            raise ValueError("Choose the state of residence to verify.")
        location = (canonical_state, location[1])
        condition = condition_from_form(claim, "REGISTERED_RESIDENCE_MATCH", classes=location)
    else:
        condition = condition_from_form(claim, operator, low, high, classes)
    if claim in CONSENT_CLAIMS:
        normalized = "CONSENT_REQUIRED"
        requirement = ("Supplied location matches the registered residence"
                       if claim == ClaimCode.REGISTERED_RESIDENCE else CLAIM_CATALOG[claim].label)
    else:
        # Validate without accessing a trusted source.
        normalized = validate_condition(claim, condition)
        requirement = condition_label(claim, normalized)
    return PreparedRequest(claim, clean_identifier, condition, normalized, requirement, clean_purpose)


def validate_condition(claim: ClaimCode, condition: Condition) -> str:
    op = condition.operator.upper()
    if claim == ClaimCode.AGE_COMPARE:
        if op not in {">", ">=", "<", "<=", "BETWEEN"}:
            raise ValueError("Choose an age requirement.")
        try:
            low = int(condition.threshold_low)
            high = int(condition.threshold_high) if op == "BETWEEN" else None
        except (TypeError, ValueError):
            raise ValueError("Enter an age between 0 and 120.") from None
        if not 0 <= low <= 120 or (high is not None and (not 0 <= high <= 120 or low > high)):
            raise ValueError("Enter a valid age or age range between 0 and 120.")
        return f"BETWEEN {low} AND {high}" if high is not None else f"{op} {low}"
    allowed = {
        ClaimCode.IDENTITY_STATUS: {"RECORD_CONFIRMED"},
        ClaimCode.LICENCE_STATUS: {"IS_VALID", "IS_EXPIRED", "IS_SUSPENDED"},
        ClaimCode.NAME_MATCH: {"NAME_MATCH"},
    }
    if claim in allowed:
        if op not in allowed[claim]:
            raise ValueError("Choose an available requirement.")
        return op
    if claim == ClaimCode.LICENCE_CLASS:
        requested = tuple(sorted(set(condition.allowed_values))) if op == "IN_SET" else (str(condition.threshold_low).upper(),)
        if op not in {"EQUALS", "IN_SET"} or not requested or any(x not in {"A", "B", "C", "D", "E"} for x in requested):
            raise ValueError("Choose at least one valid licence class.")
        return f"EQUALS {requested[0]}" if op == "EQUALS" else f"IN_SET {','.join(requested)}"
    raise ValueError("Choose an available verification.")


def create_submission(conn, organisation_id: int, claim: ClaimCode) -> str:
    token = new_token()
    execute(conn, """INSERT INTO verification_submissions
        (token_hash,organisation_id,claim_code,expires_at) VALUES (%s,%s,%s,%s)""",
        (digest_token(token), organisation_id, claim.value, utcnow_naive() + timedelta(minutes=15)))
    conn.commit()
    return token


def resolve_subject(conn, prepared: PreparedRequest) -> dict | None:
    national_source = prepared.claim in IDENTITY_CLAIMS or (
        prepared.claim == ClaimCode.NAME_MATCH and prepared.identifier.isdigit())
    if national_source:
        row = fetch_one(conn, """SELECT citizen_id,registered_phone,identity_status,record_status
            FROM citizens WHERE synthetic_nin=%s""", (prepared.identifier,))
        if row and prepared.claim != ClaimCode.IDENTITY_STATUS and row["record_status"] != "ACTIVE":
            return None
        if row:
            row.update({"subject_authority": "NATIONAL_ID", "source_record_id": row["citizen_id"]})
        return row
    row = fetch_one(conn, """SELECT licence_record_id FROM licences
        WHERE licence_number=%s AND record_status='ACTIVE'""", (prepared.identifier,))
    if row:
        row.update({"citizen_id": None, "registered_phone": None,
                    "subject_authority": "DRIVING_LICENCE", "source_record_id": row["licence_record_id"]})
    return row


def deny_inference_attempt(conn, organisation_id: int, pseudonym: str,
                           claim_code: str, reason_code: str, submission_hash: str):
    audit(conn, "POLICY_DECISION", "ORGANISATION", organisation_id, pseudonym, {
        "claim_code": claim_code, "decision": "DENY_INFERENCE_RISK",
        "reason_code": reason_code,
    })
    execute(conn, """UPDATE verification_submissions
        SET consumed_at=UTC_TIMESTAMP(),denial_code='DENY_INFERENCE_RISK',denial_message=%s
        WHERE token_hash=%s""", (BLOCK_MESSAGE, submission_hash))
    conn.commit()
    return None, BLOCK_MESSAGE


def fail_unavailable_service(conn, service_code: str, organisation_id: int):
    record_unavailable(conn, service_code, "ORGANISATION", organisation_id)
    conn.commit()
    raise TrustedSourceUnavailable(service_code)


def public_reference() -> str:
    return "VR-" + new_token().replace("_", "").replace("-", "")[:16].upper()


def submit_request(conn, organisation_id: int, token: str, prepared: PreparedRequest,
                   policy_engine=None, verification_engine=None) -> tuple[int | None, str | None]:
    if prepared.claim == ClaimCode.AGE_COMPARE:
        acquire_age_guard(conn, organisation_id, prepared.identifier)
    submission_hash = digest_token(token)
    submission = fetch_one(conn, """SELECT * FROM verification_submissions
        WHERE token_hash=%s AND organisation_id=%s FOR UPDATE""", (submission_hash, organisation_id))
    if not submission or submission["expires_at"] <= utcnow_naive() or submission["claim_code"] != prepared.claim.value:
        raise ValueError("This review has expired. Please start a new verification.")
    if submission["verification_id"]:
        return submission["verification_id"], None
    if submission.get("denial_message"):
        return None, submission["denial_message"]

    policy = (policy_engine or PolicyEngine()).decide(organisation_id, prepared.claim)
    if not policy.permitted:
        return None, policy.message

    source_service = ("NATIONAL_ID" if prepared.claim in IDENTITY_CLAIMS or
                      (prepared.claim == ClaimCode.NAME_MATCH and prepared.identifier.isdigit())
                      else "DRIVING_LICENCE")
    if not is_available(conn, source_service):
        fail_unavailable_service(conn, source_service, organisation_id)

    subject = resolve_subject(conn, prepared)
    identity_failure_reason = None
    if prepared.claim == ClaimCode.IDENTITY_STATUS:
        if not subject:
            identity_failure_reason = "NO_MATCHING_IDENTITY_RECORD"
        elif subject["record_status"] != "ACTIVE":
            identity_failure_reason = "IDENTITY_RECORD_INACTIVE"
        elif subject["identity_status"] == "REVOKED":
            identity_failure_reason = "IDENTITY_RECORD_REVOKED"
    unconfirmed_match = prepared.claim == ClaimCode.NAME_MATCH and not subject
    if unconfirmed_match:
        identity_failure_reason = ("NO_MATCHING_IDENTITY_RECORD" if prepared.identifier.isdigit()
                                   else "NO_MATCHING_LICENCE_RECORD")
    unconfirmed_identity = identity_failure_reason is not None
    if not subject and not unconfirmed_identity:
        raise InvalidVerificationRequest("No eligible record was found for this verification.")
    if unconfirmed_identity and not subject:
        citizen_id = source_record_id = None
        authority = ("NATIONAL_ID" if prepared.identifier.isdigit() else "DRIVING_LICENCE")
        pseudonym = unconfirmed_subject_reference(organisation_id, prepared.identifier)
    else:
        citizen_id = subject["citizen_id"]
        authority = subject["subject_authority"]
        source_record_id = subject["source_record_id"]
        pseudonym = subject_reference(organisation_id, source_record_id, authority=authority)
    reference = public_reference()
    now = utcnow_naive()

    if prepared.claim == ClaimCode.AGE_COMPARE:
        attempt = reserve_age_attempt(conn, organisation_id, pseudonym, now=now)
        if not attempt.allowed:
            return deny_inference_attempt(conn, organisation_id, pseudonym,
                                          prepared.claim.value, attempt.reason_code, submission_hash)

    if policy.requires_approval:
        result_code, issued_at, expires_at = "PENDING", None, now + CONSENT_TTL
        normalized = "CONSENT_REQUIRED"
    elif unconfirmed_identity:
        result_code = "CONDITION_NOT_SATISFIED"
        normalized = "NAME_MATCH" if prepared.claim == ClaimCode.NAME_MATCH else "RECORD_CONFIRMED"
        issued_at = now
        expires_at = issued_at + TTL_BY_CLASS["MEDIUM"]
    else:
        evaluation = (verification_engine or VerificationEngine()).evaluate(
            prepared.claim, prepared.identifier, prepared.condition)
        result_code = evaluation.result.value
        normalized = evaluation.normalized_condition
        issued_at = evaluation.evaluated_at.replace(tzinfo=None)
        expires_at = issued_at + TTL_BY_CLASS[evaluation.ttl_class.value]

    execute(conn, """INSERT INTO verifications
        (public_reference,submission_reference,organisation_id,citizen_id,subject_authority,source_record_id,subject_reference,
         claim_code,condition_expression,purpose,policy_decision,policy_reason,internal_reason_code,result,issued_at,expires_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (reference, submission_hash, organisation_id, citizen_id, authority, source_record_id, pseudonym,
         prepared.claim.value, normalized, prepared.purpose, policy.code.value,
         policy.reason_code, identity_failure_reason, result_code, issued_at, expires_at))
    verification_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]

    if policy.requires_approval:
        execute(conn, """INSERT INTO consent_requests
            (verification_id,citizen_id,organisation_id,claim_code,purpose,expires_at)
            VALUES (%s,%s,%s,%s,%s,%s)""",
            (verification_id, citizen_id, organisation_id, prepared.claim.value, prepared.purpose, expires_at))
        consent_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
        if prepared.claim == ClaimCode.REGISTERED_RESIDENCE:
            ciphertext, nonce = encrypt_request_context(
                {"state": prepared.condition.allowed_values[0],
                 "lga": prepared.condition.allowed_values[1]},
                consent_id, verification_id, organisation_id, citizen_id)
            execute(conn, """INSERT INTO consent_request_contexts
                (consent_request_id,ciphertext,nonce) VALUES (%s,%s,%s)""",
                (consent_id, ciphertext, nonce))
        delivery_status = queue_consent_sms(conn, consent_id, citizen_id, subject["registered_phone"], expires_at)
        audit(conn, "CONSENT_SENT", "SYSTEM", None, reference,
              {"claim_code": prepared.claim.value, "delivery": delivery_status})
    else:
        if prepared.claim == ClaimCode.AGE_COMPARE:
            finalize_age_attempt(conn, organisation_id, pseudonym, prepared.condition.operator,
                                 prepared.condition.threshold_low, prepared.condition.threshold_high)
        audit_detail = {"claim_code": prepared.claim.value, "result": result_code}
        if identity_failure_reason:
            audit_detail["internal_reason_code"] = identity_failure_reason
        audit(conn, "RESULT_GENERATED", "ORGANISATION", organisation_id, reference, audit_detail)
        sign_completed_result(conn, verification_id)
    audit(conn, "VERIFICATION_REQUESTED", "ORGANISATION", organisation_id, reference,
          {"claim_code": prepared.claim.value})
    execute(conn, """UPDATE verification_submissions SET consumed_at=UTC_TIMESTAMP(),verification_id=%s
        WHERE token_hash=%s""", (verification_id, submission_hash))
    conn.commit()
    return verification_id, None


def queue_consent_sms(conn, consent_id: int, citizen_id: int, phone: str, expires_at, *, failed=False) -> str:
    status = "FAILED" if failed or not is_available(conn, "SMS") else "SENT"
    execute(conn, """INSERT INTO sms_deliveries
        (citizen_id,consent_request_id,recipient_mask,message_type,delivery_status,
         delivery_attempted_at,delivered_at,failure_code,expires_at)
        VALUES (%s,%s,%s,'CONSENT',%s,UTC_TIMESTAMP(),%s,%s,%s)""",
        (citizen_id, consent_id, mask_phone(phone), status,
         None if status == "FAILED" else utcnow_naive(),
         "PROVIDER_UNAVAILABLE" if status == "FAILED" else None, expires_at))
    if status == "FAILED":
        record_unavailable(conn, "SMS", "SYSTEM", None, str(consent_id))
    return status


def display_verification(row: dict) -> dict:
    row = dict(row)
    claim = ClaimCode(row["claim_code"])
    if row["result"] == "PENDING" and row.get("expires_at") and row["expires_at"] <= utcnow_naive():
        row["result"] = "EXPIRED"
    row["display_name"] = CLAIM_CATALOG[claim].label
    row["admin_failure_reason"] = ADMIN_FAILURE_REASONS.get(row.get("internal_reason_code"))
    row["requirement"] = ("Supplied location matches the registered residence"
                          if claim == ClaimCode.REGISTERED_RESIDENCE else
                          CLAIM_CATALOG[claim].label.removeprefix("Request ").capitalize()
                          if row["condition_expression"] in {"CONSENT_REQUIRED", "DISCLOSED_WITH_CONSENT"}
                          else condition_label(claim, row["condition_expression"]))
    if claim in CONSENT_CLAIMS and row.get("consent_status") == "EXPIRED":
        row["result"] = "EXPIRED"
    row["outcome"] = ({
        "CONDITION_SATISFIED": "Information provided",
        "CONDITION_NOT_SATISFIED": "Information unavailable",
        "PENDING": "Awaiting the citizen's approval",
        "EXPIRED": "The approval request has expired. Please create a new verification request.",
        "DENIED": "The citizen declined this request",
    } if claim in DISCLOSURE_CLAIMS else {
        "CONDITION_SATISFIED": "Identity record confirmed" if claim == ClaimCode.IDENTITY_STATUS else "Requirement met",
        "CONDITION_NOT_SATISFIED": "Identity record not confirmed" if claim == ClaimCode.IDENTITY_STATUS else "Requirement not met",
        "PENDING": "Awaiting the citizen's approval",
        "EXPIRED": "The approval request has expired. Please create a new verification request.",
        "DENIED": "Verification unavailable",
    })[row["result"]]
    if claim == ClaimCode.NAME_MATCH and row["result"] in {"CONDITION_SATISFIED", "CONDITION_NOT_SATISFIED"}:
        row["outcome"] = "Name match confirmed" if row["result"] == "CONDITION_SATISFIED" else "Name match not confirmed"
    if claim == ClaimCode.REGISTERED_RESIDENCE and row["result"] in {"CONDITION_SATISFIED", "CONDITION_NOT_SATISFIED"}:
        row["outcome"] = "Residence confirmed" if row["result"] == "CONDITION_SATISFIED" else "Residence not confirmed"
    return row
