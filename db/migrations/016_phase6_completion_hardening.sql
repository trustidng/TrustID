-- Phase 6 completion hardening: privacy-safe global protection for the public
-- authenticity endpoint. No IP address, token, or visitor identifier is kept.

CREATE TABLE authenticity_rate_limits (
    bucket_start DATETIME PRIMARY KEY,
    request_count INT UNSIGNED NOT NULL DEFAULT 0,
    event_recorded BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;
