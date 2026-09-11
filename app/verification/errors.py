class VerificationError(Exception):
    code = "VERIFICATION_ERROR"
    safe_message = "The verification could not be completed."
    status_code = 400

    def __init__(self, internal_detail: str | None = None):
        super().__init__(self.safe_message)
        self.internal_detail = internal_detail


class InvalidVerificationRequest(VerificationError):
    code = "INVALID_VERIFICATION_REQUEST"
    safe_message = "Please check the verification details and try again."


class SubjectNotFound(VerificationError):
    code = "SUBJECT_NOT_FOUND"
    safe_message = "No eligible record was found for this verification."
    status_code = 404


class ConsentRequired(VerificationError):
    code = "CONSENT_REQUIRED"
    safe_message = "Citizen approval is required before this information can be requested."
    status_code = 409


class TrustedSourceUnavailable(VerificationError):
    code = "TRUSTED_SOURCE_UNAVAILABLE"
    safe_message = "The verification service is temporarily unavailable. Please try again later."
    status_code = 503

    def __init__(self, source: str | None = None):
        if source == "NATIONAL_ID":
            self.safe_message = "The identity verification service is temporarily unavailable. Please try again later."
        elif source == "DRIVING_LICENCE":
            self.safe_message = "The driving licence verification service is temporarily unavailable. Please try again later."
        super().__init__(source)
