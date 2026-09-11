-- Bind each delivered message to the handset session that received it.
-- Changing the handset number creates a new session and therefore a clean
-- visible inbox. Security delivery records remain until their normal cleanup.

ALTER TABLE sms_deliveries
    ADD COLUMN phone_session_id BIGINT NULL AFTER challenge_id,
    ADD CONSTRAINT fk_sms_phone_session FOREIGN KEY (phone_session_id)
        REFERENCES phone_sessions(id) ON DELETE SET NULL,
    ADD INDEX idx_sms_phone_inbox (phone_session_id, created_at);

