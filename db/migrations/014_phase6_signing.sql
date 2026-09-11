-- Phase 6 signing, key rotation, shareable receipt lookup, and tamper detection.

ALTER TABLE organisations
    ADD COLUMN public_reference VARCHAR(20) NULL AFTER id;

UPDATE organisations SET public_reference=CONCAT('ORG-',LPAD(id,8,'0'))
WHERE public_reference IS NULL;

ALTER TABLE organisations
    MODIFY COLUMN public_reference VARCHAR(20) NOT NULL,
    ADD UNIQUE INDEX uq_organisation_public_reference (public_reference);

CREATE TABLE signing_keys (
    key_id VARCHAR(64) PRIMARY KEY,
    algorithm ENUM('Ed25519') NOT NULL DEFAULT 'Ed25519',
    public_key_b64 CHAR(44) NOT NULL,
    status ENUM('ACTIVE','RETIRED','REVOKED') NOT NULL,
    activated_at DATETIME NULL,
    retired_at DATETIME NULL,
    revoked_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_signing_key_status (status)
) ENGINE=InnoDB;

ALTER TABLE receipts
    ADD COLUMN verification_token CHAR(43) NULL AFTER transaction_id,
    ADD COLUMN signing_key_id VARCHAR(64) NULL AFTER signature,
    ADD COLUMN algorithm ENUM('Ed25519') NULL AFTER signing_key_id,
    ADD UNIQUE INDEX uq_receipt_token (verification_token),
    ADD UNIQUE INDEX uq_receipt_verification (verification_id),
    ADD CONSTRAINT fk_receipt_signing_key FOREIGN KEY (signing_key_id) REFERENCES signing_keys(key_id);

ALTER TABLE audit_log MODIFY COLUMN event_type ENUM(
    'ORG_APPLICATION_SUBMITTED','ORG_APPROVED','ORG_REJECTED','ORG_SUSPENDED','ORG_REINSTATED',
    'ORG_LOGIN','ORG_LOGIN_FAILED','VERIFICATION_REQUESTED','POLICY_DECISION',
    'CONSENT_SENT','CONSENT_APPROVED','CONSENT_REJECTED','CONSENT_EXPIRED',
    'RESULT_GENERATED','RESULT_SIGNED','RATE_LIMIT_TRIGGERED','INFERENCE_RISK_FLAGGED',
    'PIN_RESET_REQUESTED','PIN_RESET_COMPLETED','ACCOUNT_ACTIVATED',
    'CATEGORY_CREATED','CATEGORY_UPDATED','CATEGORY_PERMISSIONS_UPDATED',
    'ADMIN_CREATED','ADMIN_ACTIVATED','ADMIN_DEACTIVATED','ADMIN_PASSWORD_RESET',
    'ADMIN_ROLE_CHANGED','ADMIN_VERIFICATION_HISTORY_VIEWED',
    'SIGNING_KEY_CREATED','SIGNING_KEY_ACTIVATED','SIGNING_KEY_RETIRED','SIGNING_KEY_REVOKED',
    'RESULT_AUTHENTICITY_CHECKED'
) NOT NULL;
