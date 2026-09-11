-- Shared TrustID Phone context for Messages and USSD access.
-- The token is stored only as a hash. The phone number is transport-layer
-- context and is never copied into verification, receipt, or audit records.

CREATE TABLE phone_sessions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    token_hash CHAR(64) NOT NULL UNIQUE,
    phone_number VARCHAR(20) NOT NULL,
    citizen_id INT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    last_active_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at DATETIME NULL,
    FOREIGN KEY (citizen_id) REFERENCES citizens(citizen_id),
    INDEX idx_phone_session_lookup (token_hash, expires_at, revoked_at),
    INDEX idx_phone_session_citizen (citizen_id)
) ENGINE=InnoDB;

