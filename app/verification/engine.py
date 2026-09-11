from datetime import date, datetime, timezone
import unicodedata

from .adapters import IdentitySourceAdapter, LicenceSourceAdapter
from .catalog import CLAIM_CATALOG
from .contracts import ClaimCode, Condition, EvaluationResult, ResultCode
from .errors import ConsentRequired, InvalidVerificationRequest


AGE_OPERATORS = {">", ">=", "<", "<=", "BETWEEN"}
IDENTITY_OPERATORS = {"RECORD_CONFIRMED"}
NAME_MATCH_OPERATORS = {"NAME_MATCH"}
LICENCE_STATUS_OPERATORS = {"IS_VALID", "IS_EXPIRED", "IS_SUSPENDED"}
LICENCE_CLASS_OPERATORS = {"EQUALS", "IN_SET"}
LICENCE_CLASSES = {"A", "B", "C", "D", "E"}


def age_on(date_of_birth: date, as_of: date) -> int:
    if date_of_birth > as_of:
        raise InvalidVerificationRequest("date of birth is in the future")
    return as_of.year - date_of_birth.year - ((as_of.month, as_of.day) < (date_of_birth.month, date_of_birth.day))


class VerificationEngine:
    def __init__(self, identity_source=None, licence_source=None):
        self.identity_source = identity_source or IdentitySourceAdapter()
        self.licence_source = licence_source or LicenceSourceAdapter()

    def evaluate(
        self,
        claim_code: ClaimCode | str,
        subject_identifier: str,
        condition: Condition,
        *,
        as_of: date | None = None,
    ) -> EvaluationResult:
        try:
            claim = ClaimCode(claim_code)
        except ValueError:
            raise InvalidVerificationRequest("unknown claim") from None
        if not isinstance(subject_identifier, str) or not subject_identifier.strip() or len(subject_identifier) > 64:
            raise InvalidVerificationRequest("invalid subject identifier")
        if claim in {ClaimCode.FULL_LEGAL_NAME, ClaimCode.STATE_OF_ORIGIN, ClaimCode.RESIDENTIAL_ADDRESS,
                     ClaimCode.REGISTERED_RESIDENCE}:
            raise ConsentRequired()

        evaluation_date = as_of or datetime.now(timezone.utc).date()
        evaluated_at = datetime.now(timezone.utc)
        if claim in {ClaimCode.AGE_COMPARE, ClaimCode.IDENTITY_STATUS}:
            record = self.identity_source.get_identity(subject_identifier.strip())
            satisfied, normalized = self._evaluate_identity(claim, record, condition, evaluation_date)
            authority = "NATIONAL_ID"
        elif claim == ClaimCode.NAME_MATCH and subject_identifier.strip().isdigit():
            record = self.identity_source.get_identity(subject_identifier.strip())
            satisfied, normalized = self._evaluate_name(record.surname, record.first_name, record.middle_name, condition)
            authority = "NATIONAL_ID"
        elif claim == ClaimCode.NAME_MATCH:
            record = self.licence_source.get_licence(subject_identifier.strip())
            satisfied, normalized = self._evaluate_name(
                record.holder_surname, record.holder_first_name, record.holder_middle_name, condition)
            authority = "DRIVING_LICENCE"
        else:
            record = self.licence_source.get_licence(subject_identifier.strip())
            satisfied, normalized = self._evaluate_licence(claim, record, condition, evaluation_date)
            authority = "DRIVING_LICENCE"
        return EvaluationResult(
            claim_code=claim,
            normalized_condition=normalized,
            result=ResultCode.CONDITION_SATISFIED if satisfied else ResultCode.CONDITION_NOT_SATISFIED,
            evaluated_at=evaluated_at,
            ttl_class=CLAIM_CATALOG[claim].ttl_class,
            source_authority=authority,
            source_record_id=record.citizen_id if authority == "NATIONAL_ID" else record.licence_record_id,
            photograph_reference=record.photograph_reference,
            citizen_id=record.citizen_id if authority == "NATIONAL_ID" else None,
        )

    @staticmethod
    def _name_component(value: str | None) -> str:
        decomposed = unicodedata.normalize("NFKD", value or "")
        return "".join(char.casefold() for char in decomposed
                       if not unicodedata.combining(char) and char.isalnum())

    def _evaluate_name(self, surname, first_name, middle_name, condition):
        if condition.operator.strip().upper() not in NAME_MATCH_OPERATORS or len(condition.allowed_values) != 3:
            raise InvalidVerificationRequest("invalid name-match condition")
        supplied_surname, supplied_first, supplied_middle = condition.allowed_values
        required = (self._name_component(surname), self._name_component(first_name))
        supplied = (self._name_component(supplied_surname), self._name_component(supplied_first))
        matched = required == supplied
        if supplied_middle:
            matched = matched and self._name_component(middle_name) == self._name_component(supplied_middle)
        return matched, "NAME_MATCH"

    def _evaluate_identity(self, claim, record, condition, evaluation_date):
        operator = condition.operator.strip().upper()
        if claim == ClaimCode.AGE_COMPARE:
            if operator not in AGE_OPERATORS:
                raise InvalidVerificationRequest("unsupported age operator")
            age = age_on(record.date_of_birth, evaluation_date)
            low = self._age_value(condition.threshold_low)
            if operator == "BETWEEN":
                high = self._age_value(condition.threshold_high)
                if low > high:
                    raise InvalidVerificationRequest("age range is reversed")
                return low <= age <= high, f"BETWEEN {low} AND {high}"
            if condition.threshold_high is not None:
                raise InvalidVerificationRequest("unexpected upper age threshold")
            comparisons = {">": age > low, ">=": age >= low, "<": age < low, "<=": age <= low}
            return comparisons[operator], f"{operator} {low}"

        if operator not in IDENTITY_OPERATORS or condition.threshold_low is not None or condition.threshold_high is not None or condition.allowed_values:
            raise InvalidVerificationRequest("invalid identity-status condition")
        return record.record_status == "ACTIVE" and record.identity_status != "REVOKED", operator

    def _evaluate_licence(self, claim, record, condition, evaluation_date):
        operator = condition.operator.strip().upper()
        if claim == ClaimCode.LICENCE_STATUS:
            if operator not in LICENCE_STATUS_OPERATORS or condition.threshold_low is not None or condition.threshold_high is not None or condition.allowed_values:
                raise InvalidVerificationRequest("invalid licence-status condition")
            issued = record.issue_date <= evaluation_date
            expired = record.expiry_date < evaluation_date or record.licence_status == "EXPIRED"
            outcomes = {
                "IS_VALID": record.licence_status == "VALID" and issued and not expired,
                "IS_EXPIRED": expired,
                "IS_SUSPENDED": record.licence_status == "SUSPENDED",
            }
            return outcomes[operator], operator

        if operator not in LICENCE_CLASS_OPERATORS or condition.threshold_high is not None:
            raise InvalidVerificationRequest("invalid licence-class condition")
        if operator == "EQUALS":
            requested = str(condition.threshold_low or "").strip().upper()
            if requested not in LICENCE_CLASSES or condition.allowed_values:
                raise InvalidVerificationRequest("invalid licence class")
            return record.licence_class == requested, f"EQUALS {requested}"
        if condition.threshold_low is not None:
            raise InvalidVerificationRequest("unexpected licence-class value")
        requested_set = tuple(sorted({str(value).strip().upper() for value in condition.allowed_values}))
        if not requested_set or any(value not in LICENCE_CLASSES for value in requested_set):
            raise InvalidVerificationRequest("invalid licence class set")
        return record.licence_class in requested_set, f"IN_SET {','.join(requested_set)}"

    @staticmethod
    def _age_value(value) -> int:
        if isinstance(value, bool):
            raise InvalidVerificationRequest("invalid age threshold")
        try:
            converted = int(value)
        except (TypeError, ValueError):
            raise InvalidVerificationRequest("invalid age threshold") from None
        if str(value).strip() != str(converted) or not 0 <= converted <= 120:
            raise InvalidVerificationRequest("invalid age threshold")
        return converted
