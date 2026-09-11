-- Phase 11 demo-account identity details for administrator accountability.
ALTER TABLE admin_users
    ADD COLUMN full_name VARCHAR(150) NULL AFTER username,
    ADD COLUMN email VARCHAR(150) NULL AFTER full_name,
    ADD UNIQUE INDEX uq_admin_email (email);
