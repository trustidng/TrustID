-- Phase 5 verifier portal: idempotent submissions, consent expiry, and
-- persistent privacy-safe SMS inboxes. Forward-only and data preserving.

ALTER TABLE verifications
    ADD COLUMN public_reference VARCHAR(30) NULL AFTER id,
    ADD COLUMN submission_reference CHAR(64) NULL AFTER public_reference,
    ADD UNIQUE INDEX uq_verification_public_reference (public_reference),
    ADD UNIQUE INDEX uq_verification_submission (submission_reference),
    ADD INDEX idx_verifications_org_created (organisation_id, created_at);

CREATE TABLE verification_submissions (
    token_hash CHAR(64) PRIMARY KEY,
    organisation_id INT NOT NULL,
    claim_code VARCHAR(30) NOT NULL,
    expires_at DATETIME NOT NULL,
    consumed_at DATETIME NULL,
    verification_id INT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (organisation_id) REFERENCES organisations(id),
    FOREIGN KEY (verification_id) REFERENCES verifications(id),
    INDEX idx_submission_org_expiry (organisation_id, expires_at)
) ENGINE=InnoDB;

ALTER TABLE consent_requests
    ADD COLUMN expires_at DATETIME NULL AFTER created_at,
    ADD UNIQUE INDEX uq_consent_verification (verification_id),
    ADD INDEX idx_consent_org_status (organisation_id, status, created_at);

ALTER TABLE sms_deliveries
    MODIFY COLUMN challenge_id BIGINT NULL,
    MODIFY COLUMN access_token_hash CHAR(64) NULL,
    MODIFY COLUMN code_nonce VARCHAR(64) NULL,
    ADD COLUMN citizen_id INT NULL AFTER phone_session_id,
    ADD COLUMN consent_request_id INT NULL AFTER citizen_id,
    ADD COLUMN delivery_status ENUM('PENDING','SENT','FAILED') NOT NULL DEFAULT 'SENT' AFTER message_type,
    ADD COLUMN delivery_attempted_at DATETIME NULL AFTER delivery_status,
    ADD COLUMN delivered_at DATETIME NULL AFTER delivery_attempted_at,
    ADD COLUMN failure_code VARCHAR(40) NULL AFTER delivered_at;

UPDATE sms_deliveries d
JOIN otp_challenges c ON c.id=d.challenge_id
SET d.citizen_id=c.citizen_id,
    d.delivery_attempted_at=COALESCE(d.delivery_attempted_at,d.created_at),
    d.delivered_at=COALESCE(d.delivered_at,d.created_at)
WHERE d.citizen_id IS NULL;

ALTER TABLE sms_deliveries
    ADD CONSTRAINT fk_sms_citizen FOREIGN KEY (citizen_id) REFERENCES citizens(citizen_id),
    ADD CONSTRAINT fk_sms_consent FOREIGN KEY (consent_request_id) REFERENCES consent_requests(id) ON DELETE CASCADE,
    ADD UNIQUE INDEX uq_sms_consent_request (consent_request_id),
    ADD INDEX idx_sms_citizen_inbox (citizen_id, created_at),
    ADD INDEX idx_sms_citizen_unread (citizen_id, opened_at);
