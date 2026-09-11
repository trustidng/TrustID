-- An unmatched NIN is a completed negative verification, not a malformed
-- request. It has no trusted-source record to reference.
ALTER TABLE verifications
    MODIFY COLUMN source_record_id BIGINT NULL;
