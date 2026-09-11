-- TrustID Phase 2: non-destructive authentication support.
-- Apply exactly once through: python db/migrate.py

ALTER TABLE admin_users
    ADD COLUMN failed_login_attempts INT NOT NULL DEFAULT 0,
    ADD COLUMN locked_until DATETIME NULL,
    ADD COLUMN last_login_at DATETIME NULL;

ALTER TABLE organisations
    ADD COLUMN failed_login_attempts INT NOT NULL DEFAULT 0,
    ADD COLUMN locked_until DATETIME NULL,
    ADD COLUMN last_login_at DATETIME NULL;

ALTER TABLE citizens
    ADD COLUMN failed_pin_attempts INT NOT NULL DEFAULT 0,
    ADD COLUMN locked_until DATETIME NULL,
    ADD COLUMN activated_at DATETIME NULL,
    ADD COLUMN last_login_at DATETIME NULL;

CREATE TABLE auth_sessions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    token_hash CHAR(64) NOT NULL UNIQUE,
    actor_type ENUM('ADMIN','ORGANISATION','CITIZEN') NOT NULL,
    actor_id INT NOT NULL,
    csrf_token VARCHAR(64) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    revoked_at DATETIME NULL,
    INDEX idx_auth_session_lookup (token_hash, expires_at, revoked_at),
    INDEX idx_auth_session_actor (actor_type, actor_id)
) ENGINE=InnoDB;

CREATE TABLE otp_challenges (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    citizen_id INT NOT NULL,
    purpose ENUM('ACCOUNT_ACTIVATION','PIN_RESET') NOT NULL,
    code_hash CHAR(64) NOT NULL,
    failed_attempts INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    consumed_at DATETIME NULL,
    FOREIGN KEY (citizen_id) REFERENCES citizens(citizen_id),
    INDEX idx_otp_active (citizen_id, purpose, expires_at, consumed_at)
) ENGINE=InnoDB;

