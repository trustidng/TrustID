-- TrustID Phase 2 refinement: secure SMS delivery and administrator
-- bootstrap-password replacement. Apply through: python db/migrate.py

ALTER TABLE admin_users
    ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN password_changed_at DATETIME NULL;

CREATE TABLE sms_deliveries (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    challenge_id BIGINT NOT NULL UNIQUE,
    access_token_hash CHAR(64) NOT NULL UNIQUE,
    code_nonce VARCHAR(64) NOT NULL,
    recipient_mask VARCHAR(24) NOT NULL,
    message_type ENUM('ACCOUNT_ACTIVATION','PIN_RESET','CONSENT','SECURITY_ALERT') NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    opened_at DATETIME NULL,
    FOREIGN KEY (challenge_id) REFERENCES otp_challenges(id) ON DELETE CASCADE,
    INDEX idx_sms_access (access_token_hash, expires_at)
) ENGINE=InnoDB;

