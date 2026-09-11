-- TrustID — Phase 1 Schema
-- Built directly against Phase0_Architecture_Freeze.md — do not add fields here
-- without updating that document first.
--
-- Idempotent: safe to re-run for a clean demo reset.

SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS request_history;
DROP TABLE IF EXISTS inference_tracking;      -- enhancement-tier, created empty for forward compat
DROP TABLE IF EXISTS audit_log;
DROP TABLE IF EXISTS consent_requests;
DROP TABLE IF EXISTS receipts;
DROP TABLE IF EXISTS verifications;
DROP TABLE IF EXISTS licences;
DROP TABLE IF EXISTS citizens;
DROP TABLE IF EXISTS organisations;
DROP TABLE IF EXISTS admin_users;

SET FOREIGN_KEY_CHECKS = 1;

-- ============================================================
-- Actors
-- ============================================================

CREATE TABLE admin_users (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    username        VARCHAR(64) NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE organisations (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    business_name           VARCHAR(150) NOT NULL,
    email                   VARCHAR(150) NOT NULL UNIQUE,
    phone                   VARCHAR(20) NOT NULL,
    category                ENUM('RETAIL','PROGRAMME_OPERATOR','GOVERNMENT','FINANCIAL','TRANSPORT_LOGISTICS') NOT NULL,
    status                  ENUM('PENDING','APPROVED','REJECTED','SUSPENDED') NOT NULL DEFAULT 'PENDING',
    registration_reference  VARCHAR(100) NULL,
    intended_use            TEXT NULL,
    password_hash           VARCHAR(255) NOT NULL,
    status_reason           VARCHAR(255) NULL,      -- shown to org on rejection/suspension
    reviewed_by_admin_id    INT NULL,
    reviewed_at             DATETIME NULL,
    created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (reviewed_by_admin_id) REFERENCES admin_users(id)
) ENGINE=InnoDB;

-- ============================================================
-- Synthetic National Identity Authority
-- ============================================================

CREATE TABLE citizens (
    citizen_id          INT AUTO_INCREMENT PRIMARY KEY,
    synthetic_nin        VARCHAR(20) NOT NULL UNIQUE,
    full_name            VARCHAR(150) NOT NULL,
    date_of_birth        DATE NOT NULL,
    registered_phone     VARCHAR(20) NOT NULL UNIQUE,
    identity_status      ENUM('VERIFIED','ACTIVE','REVOKED') NOT NULL DEFAULT 'VERIFIED',
    record_status        ENUM('ACTIVE','INACTIVE') NOT NULL DEFAULT 'ACTIVE',
    state_of_residence   VARCHAR(50) NOT NULL,
    -- citizen web/USSD account fields (Phase 2)
    pin_hash             VARCHAR(255) NULL,
    account_activated    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_citizens_phone (registered_phone)
) ENGINE=InnoDB;

-- ============================================================
-- Synthetic Driver Licensing Authority bootstrap shape. Migration 018 copies
-- the legacy link into standalone holder fields, then removes this relationship.
-- ============================================================

CREATE TABLE licences (
    licence_number      VARCHAR(20) PRIMARY KEY,
    citizen_reference   INT NOT NULL,
    licence_class       ENUM('A','B','C','D','E') NOT NULL,
    issue_date          DATE NOT NULL,
    expiry_date         DATE NOT NULL,
    licence_status       ENUM('VALID','EXPIRED','SUSPENDED') NOT NULL DEFAULT 'VALID',
    FOREIGN KEY (citizen_reference) REFERENCES citizens(citizen_id),
    INDEX idx_licences_citizen (citizen_reference)
) ENGINE=InnoDB;

-- ============================================================
-- Verifications
-- citizen_id here is internal/server-side only — never returned
-- to a verifier. subject_reference (org-scoped HMAC pseudonym)
-- is what's verifier-facing. Raw synthetic_nin/licence_number are
-- NEVER written to this table — they are transient lookup inputs.
-- ============================================================

CREATE TABLE verifications (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    organisation_id     INT NOT NULL,
    citizen_id          INT NOT NULL,                 -- internal only, powers Phase 8 citizen history
    subject_reference   VARCHAR(20) NOT NULL,           -- HMAC(secret, org_id||citizen_id), verifier-facing
    claim_code          VARCHAR(30) NOT NULL,           -- extended by later migrations
    condition_expression VARCHAR(100) NOT NULL,          -- e.g. "BETWEEN 18 AND 30", "IS_VALID"
    purpose             VARCHAR(255) NOT NULL,
    policy_decision      ENUM('ALLOW_INSTANT','REQUIRE_CONSENT','REQUIRE_STRONG_CONSENT',
                               'DENY_ORG_NOT_APPROVED','DENY_UNAUTHORIZED_CLAIM',
                               'DENY_RATE_LIMIT','DENY_INFERENCE_RISK') NOT NULL,
    policy_reason        VARCHAR(255) NOT NULL,
    result               ENUM('CONDITION_SATISFIED','CONDITION_NOT_SATISFIED','PENDING','DENIED') NOT NULL,
    issued_at            DATETIME NULL,
    expires_at           DATETIME NULL,
    created_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (organisation_id) REFERENCES organisations(id),
    FOREIGN KEY (citizen_id) REFERENCES citizens(citizen_id),
    INDEX idx_verifications_org_subject (organisation_id, subject_reference),
    INDEX idx_verifications_citizen (citizen_id)
) ENGINE=InnoDB;

-- ============================================================
-- Receipts — verifier-facing proof. Distinct from audit_log.
-- ============================================================

CREATE TABLE receipts (
    transaction_id       VARCHAR(30) PRIMARY KEY,        -- e.g. VR-2026-000184, matches verification_id in signed payload
    verification_id      INT NOT NULL,
    claim_code           VARCHAR(30) NOT NULL,
    condition_expression VARCHAR(100) NOT NULL,
    result                ENUM('CONDITION_SATISFIED','CONDITION_NOT_SATISFIED') NOT NULL,
    issued_at             DATETIME NOT NULL,
    expires_at            DATETIME NOT NULL,
    organisation_id       INT NOT NULL,
    subject_reference     VARCHAR(20) NOT NULL,
    canonical_payload      TEXT NOT NULL,                 -- exact signed string — never regenerate-and-hope
    signature              TEXT NOT NULL,
    integrity_status        ENUM('VALID','TAMPERED','EXPIRED') NOT NULL DEFAULT 'VALID',
    FOREIGN KEY (verification_id) REFERENCES verifications(id),
    FOREIGN KEY (organisation_id) REFERENCES organisations(id)
) ENGINE=InnoDB;

-- ============================================================
-- Consent requests (Phase 8) — multi-channel resolution,
-- first valid decision wins (enforced at the application layer
-- via UPDATE ... WHERE status = 'PENDING', not read-then-write)
-- ============================================================

CREATE TABLE consent_requests (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    verification_id      INT NOT NULL,
    citizen_id           INT NOT NULL,
    organisation_id       INT NOT NULL,
    claim_code            VARCHAR(30) NOT NULL,
    purpose               VARCHAR(255) NOT NULL,
    status                 ENUM('PENDING','APPROVED','REJECTED','EXPIRED') NOT NULL DEFAULT 'PENDING',
    resolved_channel        ENUM('WEB','USSD','SMS') NULL,
    created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at              DATETIME NULL,
    FOREIGN KEY (verification_id) REFERENCES verifications(id),
    FOREIGN KEY (citizen_id) REFERENCES citizens(citizen_id),
    FOREIGN KEY (organisation_id) REFERENCES organisations(id)
) ENGINE=InnoDB;

-- ============================================================
-- Audit log — internal investigation trail. `detail` is
-- structured JSON with a per-event_type field allowlist.
-- Never contains raw synthetic_nin, licence_number, full_name,
-- or date_of_birth — only citizen_id/subject_reference and
-- org/claim/policy metadata.
-- ============================================================

CREATE TABLE audit_log (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    event_type      ENUM(
                        'ORG_APPLICATION_SUBMITTED','ORG_APPROVED','ORG_REJECTED','ORG_SUSPENDED',
                        'ORG_LOGIN','ORG_LOGIN_FAILED',
                        'VERIFICATION_REQUESTED','POLICY_DECISION',
                        'CONSENT_SENT','CONSENT_APPROVED','CONSENT_REJECTED','CONSENT_EXPIRED',
                        'RESULT_GENERATED','RESULT_SIGNED',
                        'RATE_LIMIT_TRIGGERED','INFERENCE_RISK_FLAGGED',
                        'PIN_RESET_REQUESTED','PIN_RESET_COMPLETED','ACCOUNT_ACTIVATED'
                     ) NOT NULL,
    actor_type       ENUM('ADMIN','ORGANISATION','CITIZEN','SYSTEM') NOT NULL,
    actor_id         INT NULL,
    target_reference VARCHAR(30) NULL,       -- subject_reference or org id, never a raw identifier
    detail           JSON NULL,
    timestamp        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_audit_event_type (event_type),
    INDEX idx_audit_timestamp (timestamp)
) ENGINE=InnoDB;

-- ============================================================
-- Request history — powers Phase 9's MVP volume-based counter.
-- (inference_tracking, for the enhancement-tier interval-narrowing
-- state machine, is intentionally NOT created here — add it only
-- when that phase actually starts.)
-- ============================================================

CREATE TABLE request_history (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    organisation_id     INT NOT NULL,
    subject_reference   VARCHAR(20) NOT NULL,
    claim_family        VARCHAR(20) NOT NULL,      -- e.g. 'AGE'
    operator             VARCHAR(10) NOT NULL,       -- '>', '>=', '<', '<=', 'BETWEEN'
    threshold_low         VARCHAR(20) NULL,
    threshold_high         VARCHAR(20) NULL,
    result                  ENUM('TRUE','FALSE') NOT NULL,
    timestamp               DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (organisation_id) REFERENCES organisations(id),
    INDEX idx_history_org_subject_time (organisation_id, subject_reference, timestamp)
) ENGINE=InnoDB;
