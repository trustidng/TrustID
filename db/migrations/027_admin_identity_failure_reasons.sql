-- Privacy-safe internal reason for administrator oversight. This column never
-- contains a submitted identifier or trusted-source personal information.
ALTER TABLE verifications
    ADD COLUMN internal_reason_code VARCHAR(50) NULL AFTER policy_reason;
