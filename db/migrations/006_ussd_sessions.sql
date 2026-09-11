-- Short-lived, stateful USSD conversations. Raw responses and PINs are never stored.
CREATE TABLE ussd_sessions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    token_hash CHAR(64) NOT NULL UNIQUE,
    phone_session_id BIGINT NOT NULL,
    citizen_id INT NOT NULL,
    state ENUM('MENU','AWAITING_NEW_PIN','AWAITING_PIN_CONFIRMATION','AWAITING_LOGIN_PIN','ENDED') NOT NULL DEFAULT 'MENU',
    pending_pin_hash VARCHAR(255) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    last_active_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at DATETIME NULL,
    FOREIGN KEY (phone_session_id) REFERENCES phone_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (citizen_id) REFERENCES citizens(citizen_id),
    INDEX idx_ussd_session_lookup (token_hash, expires_at, ended_at),
    INDEX idx_ussd_session_phone (phone_session_id)
) ENGINE=InnoDB;
