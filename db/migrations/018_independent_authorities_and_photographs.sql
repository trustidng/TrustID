-- Independent trusted authorities and protected synthetic identity photographs.
-- Existing signed receipts and their subject references are not modified.

ALTER TABLE citizens
    ADD COLUMN identity_photograph_reference VARCHAR(20) NULL AFTER residential_address;

UPDATE citizens
SET identity_photograph_reference=CONCAT('PHOTO-',LPAD(1+MOD(citizen_id-1,16),4,'0'))
WHERE identity_photograph_reference IS NULL;

ALTER TABLE citizens
    MODIFY COLUMN identity_photograph_reference VARCHAR(20) NOT NULL;

ALTER TABLE licences
    ADD COLUMN licence_record_id BIGINT NOT NULL AUTO_INCREMENT UNIQUE FIRST,
    ADD COLUMN holder_full_name VARCHAR(150) NULL AFTER citizen_reference,
    ADD COLUMN holder_date_of_birth DATE NULL AFTER holder_full_name,
    ADD COLUMN holder_photograph_reference VARCHAR(20) NULL AFTER holder_date_of_birth,
    ADD COLUMN record_status ENUM('ACTIVE','INACTIVE') NOT NULL DEFAULT 'ACTIVE' AFTER licence_status,
    ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP AFTER record_status,
    ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP AFTER created_at;

UPDATE licences l
JOIN citizens c ON c.citizen_id=l.citizen_reference
SET l.holder_full_name=c.full_name,
    l.holder_date_of_birth=c.date_of_birth,
    l.holder_photograph_reference=c.identity_photograph_reference;

ALTER TABLE verifications
    ADD COLUMN subject_authority ENUM('NATIONAL_ID','DRIVING_LICENCE') NULL AFTER citizen_id,
    ADD COLUMN source_record_id BIGINT NULL AFTER subject_authority;

UPDATE verifications
SET subject_authority='NATIONAL_ID',source_record_id=citizen_id
WHERE claim_code IN ('AGE_COMPARE','IDENTITY_STATUS','FULL_LEGAL_NAME','STATE_OF_ORIGIN','RESIDENTIAL_ADDRESS');

UPDATE verifications v
JOIN licences l ON l.citizen_reference=v.citizen_id
SET v.subject_authority='DRIVING_LICENCE',v.source_record_id=l.licence_record_id
WHERE v.claim_code IN ('LICENCE_STATUS','LICENCE_CLASS');

ALTER TABLE licences DROP FOREIGN KEY licences_ibfk_1;
ALTER TABLE licences DROP INDEX idx_licences_citizen;
ALTER TABLE licences
    MODIFY COLUMN holder_full_name VARCHAR(150) NOT NULL,
    MODIFY COLUMN holder_date_of_birth DATE NOT NULL,
    MODIFY COLUMN holder_photograph_reference VARCHAR(20) NOT NULL,
    DROP COLUMN citizen_reference;

ALTER TABLE verifications
    MODIFY COLUMN citizen_id INT NULL,
    MODIFY COLUMN subject_authority ENUM('NATIONAL_ID','DRIVING_LICENCE') NOT NULL,
    MODIFY COLUMN source_record_id BIGINT NOT NULL,
    ADD INDEX idx_verifications_source (subject_authority,source_record_id);

CREATE TABLE identity_photo_rate_limits (
    organisation_id INT NOT NULL,
    bucket_start DATETIME NOT NULL,
    request_count INT UNSIGNED NOT NULL DEFAULT 0,
    event_recorded BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (organisation_id,bucket_start),
    FOREIGN KEY (organisation_id) REFERENCES organisations(id)
) ENGINE=InnoDB;

ALTER TABLE audit_log MODIFY COLUMN event_type ENUM(
    'ORG_APPLICATION_SUBMITTED','ORG_APPROVED','ORG_REJECTED','ORG_SUSPENDED','ORG_REINSTATED',
    'ORG_LOGIN','ORG_LOGIN_FAILED','VERIFICATION_REQUESTED','POLICY_DECISION',
    'CONSENT_SENT','CONSENT_APPROVED','CONSENT_REJECTED','CONSENT_EXPIRED',
    'RESULT_GENERATED','RESULT_SIGNED','RATE_LIMIT_TRIGGERED','INFERENCE_RISK_FLAGGED',
    'PIN_RESET_REQUESTED','PIN_RESET_COMPLETED','ACCOUNT_ACTIVATED',
    'CATEGORY_CREATED','CATEGORY_UPDATED','CATEGORY_PERMISSIONS_UPDATED',
    'ADMIN_CREATED','ADMIN_ACTIVATED','ADMIN_DEACTIVATED','ADMIN_PASSWORD_RESET',
    'ADMIN_ROLE_CHANGED','ADMIN_VERIFICATION_HISTORY_VIEWED',
    'SIGNING_KEY_CREATED','SIGNING_KEY_ACTIVATED','SIGNING_KEY_RETIRED','SIGNING_KEY_REVOKED',
    'RESULT_AUTHENTICITY_CHECKED','IDENTITY_PHOTO_VIEWED'
) NOT NULL;
