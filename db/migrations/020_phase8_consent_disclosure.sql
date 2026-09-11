-- Phase 8 citizen decisions and encrypted controlled disclosure.

ALTER TABLE consent_requests
    ADD COLUMN wording_version VARCHAR(20) NOT NULL DEFAULT '2026-09-v1' AFTER status,
    ADD COLUMN viewed_at DATETIME NULL AFTER wording_version,
    ADD INDEX idx_consent_citizen_status (citizen_id,status,created_at);

ALTER TABLE otp_challenges
    MODIFY COLUMN purpose ENUM('ACCOUNT_ACTIVATION','PIN_RESET','CONSENT_APPROVAL') NOT NULL,
    ADD COLUMN consent_request_id INT NULL AFTER citizen_id,
    ADD COLUMN invalidated_at DATETIME NULL AFTER consumed_at,
    ADD CONSTRAINT fk_otp_consent FOREIGN KEY (consent_request_id) REFERENCES consent_requests(id) ON DELETE CASCADE,
    ADD INDEX idx_otp_consent_active (consent_request_id,purpose,expires_at,consumed_at,invalidated_at);

ALTER TABLE sms_deliveries
    MODIFY COLUMN message_type ENUM('ACCOUNT_ACTIVATION','PIN_RESET','CONSENT','CONSENT_APPROVAL_CODE','SECURITY_ALERT') NOT NULL;

CREATE TABLE controlled_disclosures (
    verification_id INT PRIMARY KEY,
    organisation_id INT NOT NULL,
    citizen_id INT NOT NULL,
    claim_code VARCHAR(30) NOT NULL,
    ciphertext BLOB NOT NULL,
    nonce BINARY(12) NOT NULL,
    key_version VARCHAR(20) NOT NULL DEFAULT 'v1',
    issued_at DATETIME NOT NULL,
    expires_at DATETIME NOT NULL,
    last_viewed_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (verification_id) REFERENCES verifications(id) ON DELETE CASCADE,
    FOREIGN KEY (organisation_id) REFERENCES organisations(id),
    FOREIGN KEY (citizen_id) REFERENCES citizens(citizen_id),
    INDEX idx_disclosure_org_expiry (organisation_id,expires_at),
    INDEX idx_disclosure_expiry (expires_at)
) ENGINE=InnoDB;

ALTER TABLE ussd_sessions
    MODIFY COLUMN state ENUM(
        'MENU','AWAITING_NEW_PIN','AWAITING_PIN_CONFIRMATION','AWAITING_LOGIN_PIN',
        'CONSENT_MENU','CONSENT_LIST','CONSENT_DETAIL','CONSENT_APPROVE_CONFIRM',
        'CONSENT_REJECT_CONFIRM','RECENT_DECISIONS','ENDED'
    ) NOT NULL DEFAULT 'MENU',
    ADD COLUMN selected_consent_id INT NULL AFTER pending_pin_hash,
    ADD COLUMN list_offset INT UNSIGNED NOT NULL DEFAULT 0 AFTER selected_consent_id,
    ADD CONSTRAINT fk_ussd_selected_consent FOREIGN KEY (selected_consent_id) REFERENCES consent_requests(id) ON DELETE SET NULL;

ALTER TABLE audit_log MODIFY COLUMN event_type ENUM(
    'ORG_APPLICATION_SUBMITTED','ORG_APPROVED','ORG_REJECTED','ORG_SUSPENDED','ORG_REINSTATED',
    'ORG_LOGIN','ORG_LOGIN_FAILED','VERIFICATION_REQUESTED','POLICY_DECISION',
    'CONSENT_SENT','CONSENT_VIEWED','CONSENT_APPROVAL_STARTED','CONSENT_CODE_SENT',
    'CONSENT_APPROVED','CONSENT_REJECTED','CONSENT_EXPIRED','DISCLOSURE_CREATED','DISCLOSURE_VIEWED',
    'RESULT_GENERATED','RESULT_SIGNED','RATE_LIMIT_TRIGGERED','INFERENCE_RISK_FLAGGED',
    'PIN_RESET_REQUESTED','PIN_RESET_COMPLETED','ACCOUNT_ACTIVATED',
    'CATEGORY_CREATED','CATEGORY_UPDATED','CATEGORY_PERMISSIONS_UPDATED',
    'ADMIN_CREATED','ADMIN_ACTIVATED','ADMIN_DEACTIVATED','ADMIN_PASSWORD_RESET',
    'ADMIN_ROLE_CHANGED','ADMIN_VERIFICATION_HISTORY_VIEWED',
    'SIGNING_KEY_CREATED','SIGNING_KEY_ACTIVATED','SIGNING_KEY_RETIRED','SIGNING_KEY_REVOKED',
    'RESULT_AUTHENTICITY_CHECKED','IDENTITY_PHOTO_VIEWED'
) NOT NULL;
