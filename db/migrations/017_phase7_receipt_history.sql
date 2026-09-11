-- Phase 7 organization receipt history, newest first.
-- Receipt data remains unchanged; this index supports scoped pagination.

ALTER TABLE receipts
    ADD INDEX idx_receipts_org_issued (organisation_id, issued_at);
