-- Database-driven organisation categories and claim permissions for Phase 4.
CREATE TABLE claim_definitions (
    claim_code VARCHAR(30) PRIMARY KEY,
    display_name VARCHAR(100) NOT NULL,
    action_type ENUM('VERIFY','REQUEST') NOT NULL,
    privacy_mode ENUM('INSTANT','CONSENT','STRONG_CONSENT') NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE organisation_categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL UNIQUE,
    description VARCHAR(255) NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE category_claim_permissions (
    category_id INT NOT NULL,
    claim_code VARCHAR(30) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (category_id, claim_code),
    FOREIGN KEY (category_id) REFERENCES organisation_categories(id) ON DELETE CASCADE,
    FOREIGN KEY (claim_code) REFERENCES claim_definitions(claim_code)
) ENGINE=InnoDB;

INSERT INTO claim_definitions (claim_code,display_name,action_type,privacy_mode) VALUES
('AGE_COMPARE','Verify age requirement','VERIFY','INSTANT'),
('IDENTITY_STATUS','Verify identity status','VERIFY','INSTANT'),
('LICENCE_STATUS','Verify driving licence status','VERIFY','INSTANT'),
('LICENCE_CLASS','Verify driving licence class','VERIFY','INSTANT'),
('FULL_LEGAL_NAME','Request legal name','REQUEST','CONSENT'),
('STATE_OF_ORIGIN','Request state of origin','REQUEST','CONSENT'),
('RESIDENTIAL_ADDRESS','Request residential address','REQUEST','STRONG_CONSENT');

INSERT INTO organisation_categories (code,name,description) VALUES
('RETAIL','Retail','Retailers and small vendors'),
('PROGRAMME_OPERATOR','Programme operator','Eligibility and support programme operators'),
('GOVERNMENT','Government','Government service organizations'),
('FINANCIAL','Financial','Banks, financial institutions and financial-service providers'),
('TRANSPORT_LOGISTICS','Transport and logistics','Transport, delivery and logistics organizations');

INSERT INTO category_claim_permissions (category_id,claim_code)
SELECT c.id, p.claim_code FROM organisation_categories c JOIN (
    SELECT 'RETAIL' code, 'AGE_COMPARE' claim_code UNION ALL
    SELECT 'RETAIL', 'IDENTITY_STATUS' UNION ALL
    SELECT 'PROGRAMME_OPERATOR', 'AGE_COMPARE' UNION ALL
    SELECT 'PROGRAMME_OPERATOR', 'IDENTITY_STATUS' UNION ALL
    SELECT 'PROGRAMME_OPERATOR', 'FULL_LEGAL_NAME' UNION ALL
    SELECT 'PROGRAMME_OPERATOR', 'STATE_OF_ORIGIN' UNION ALL
    SELECT 'GOVERNMENT', 'AGE_COMPARE' UNION ALL
    SELECT 'GOVERNMENT', 'IDENTITY_STATUS' UNION ALL
    SELECT 'GOVERNMENT', 'FULL_LEGAL_NAME' UNION ALL
    SELECT 'GOVERNMENT', 'STATE_OF_ORIGIN' UNION ALL
    SELECT 'GOVERNMENT', 'RESIDENTIAL_ADDRESS' UNION ALL
    SELECT 'FINANCIAL', 'AGE_COMPARE' UNION ALL
    SELECT 'FINANCIAL', 'IDENTITY_STATUS' UNION ALL
    SELECT 'FINANCIAL', 'FULL_LEGAL_NAME' UNION ALL
    SELECT 'FINANCIAL', 'STATE_OF_ORIGIN' UNION ALL
    SELECT 'FINANCIAL', 'RESIDENTIAL_ADDRESS' UNION ALL
    SELECT 'TRANSPORT_LOGISTICS', 'LICENCE_STATUS' UNION ALL
    SELECT 'TRANSPORT_LOGISTICS', 'LICENCE_CLASS' UNION ALL
    SELECT 'TRANSPORT_LOGISTICS', 'IDENTITY_STATUS'
) p ON p.code=c.code;

ALTER TABLE organisations ADD COLUMN category_id INT NULL AFTER category;

UPDATE organisations o JOIN organisation_categories c ON c.code=o.category
SET o.category_id=c.id;

ALTER TABLE organisations
    MODIFY COLUMN category_id INT NOT NULL,
    ADD CONSTRAINT fk_organisations_category FOREIGN KEY (category_id) REFERENCES organisation_categories(id),
    CHANGE COLUMN category legacy_category ENUM('RETAIL','PROGRAMME_OPERATOR','GOVERNMENT','FINANCIAL','TRANSPORT_LOGISTICS') NULL;

ALTER TABLE audit_log MODIFY COLUMN event_type ENUM(
    'ORG_APPLICATION_SUBMITTED','ORG_APPROVED','ORG_REJECTED','ORG_SUSPENDED',
    'ORG_LOGIN','ORG_LOGIN_FAILED','VERIFICATION_REQUESTED','POLICY_DECISION',
    'CONSENT_SENT','CONSENT_APPROVED','CONSENT_REJECTED','CONSENT_EXPIRED',
    'RESULT_GENERATED','RESULT_SIGNED','RATE_LIMIT_TRIGGERED','INFERENCE_RISK_FLAGGED',
    'PIN_RESET_REQUESTED','PIN_RESET_COMPLETED','ACCOUNT_ACTIVATED',
    'CATEGORY_CREATED','CATEGORY_UPDATED','CATEGORY_PERMISSIONS_UPDATED'
) NOT NULL;
