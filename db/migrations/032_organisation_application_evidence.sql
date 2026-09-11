ALTER TABLE organisation_categories
    ADD COLUMN registration_reference_required BOOLEAN NOT NULL DEFAULT FALSE AFTER description;

CREATE TABLE category_evidence_requirements (
    id INT AUTO_INCREMENT PRIMARY KEY,
    category_id INT NOT NULL,
    name VARCHAR(120) NOT NULL,
    instructions VARCHAR(255) NULL,
    requirement_mode ENUM('REQUIRED','ALTERNATIVE','OPTIONAL') NOT NULL DEFAULT 'REQUIRED',
    requires_document_number BOOLEAN NOT NULL DEFAULT FALSE,
    requires_expiry_date BOOLEAN NOT NULL DEFAULT FALSE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES organisation_categories(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE organisation_evidence_submissions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    organisation_id INT NOT NULL,
    requirement_id INT NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    stored_filename VARCHAR(255) NOT NULL UNIQUE,
    mime_type VARCHAR(80) NOT NULL,
    byte_size INT NOT NULL,
    sha256 CHAR(64) NOT NULL,
    document_number VARCHAR(120) NULL,
    expires_on DATE NULL,
    uploaded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (organisation_id) REFERENCES organisations(id) ON DELETE CASCADE,
    FOREIGN KEY (requirement_id) REFERENCES category_evidence_requirements(id)
) ENGINE=InnoDB;

UPDATE organisation_categories SET registration_reference_required=TRUE
WHERE code IN ('FINANCIAL','GOVERNMENT','PROGRAMME_OPERATOR','TRANSPORT_LOGISTICS');

INSERT INTO category_evidence_requirements
(category_id,name,instructions,requirement_mode,requires_document_number,requires_expiry_date,sort_order)
SELECT id,'CAC certificate or registration extract','Upload an official business registration document.','REQUIRED',TRUE,FALSE,10
FROM organisation_categories WHERE code='FINANCIAL';
INSERT INTO category_evidence_requirements
(category_id,name,instructions,requirement_mode,requires_document_number,requires_expiry_date,sort_order)
SELECT id,'Regulatory licence','Upload the licence issued by the relevant financial regulator.','REQUIRED',TRUE,TRUE,20
FROM organisation_categories WHERE code='FINANCIAL';
INSERT INTO category_evidence_requirements
(category_id,name,instructions,requirement_mode,sort_order)
SELECT id,'Government establishment evidence','Upload an establishment document or official government directory evidence.','REQUIRED',10
FROM organisation_categories WHERE code='GOVERNMENT';
INSERT INTO category_evidence_requirements
(category_id,name,instructions,requirement_mode,sort_order)
SELECT id,'Official authorization letter','A signed letter confirming this application and its intended use.','REQUIRED',20
FROM organisation_categories WHERE code='GOVERNMENT';
INSERT INTO category_evidence_requirements
(category_id,name,instructions,requirement_mode,requires_document_number,sort_order)
SELECT id,'Registration or accreditation evidence','Upload registration, accreditation or establishment evidence.','REQUIRED',TRUE,10
FROM organisation_categories WHERE code='PROGRAMME_OPERATOR';
INSERT INTO category_evidence_requirements
(category_id,name,instructions,requirement_mode,sort_order)
SELECT id,'Owner identity evidence','Accepted for an informal business or retailer.','ALTERNATIVE',10
FROM organisation_categories WHERE code='RETAIL';
INSERT INTO category_evidence_requirements
(category_id,name,instructions,requirement_mode,sort_order)
SELECT id,'Operating address or storefront evidence','Accepted as an alternative to owner identity evidence.','ALTERNATIVE',20
FROM organisation_categories WHERE code='RETAIL';
INSERT INTO category_evidence_requirements
(category_id,name,instructions,requirement_mode,requires_document_number,sort_order)
SELECT id,'Business registration','Upload the organization registration document.','REQUIRED',TRUE,10
FROM organisation_categories WHERE code='TRANSPORT_LOGISTICS';
INSERT INTO category_evidence_requirements
(category_id,name,instructions,requirement_mode,requires_document_number,requires_expiry_date,sort_order)
SELECT id,'Operator licence','Upload where a licence is applicable to your operation.','OPTIONAL',TRUE,TRUE,20
FROM organisation_categories WHERE code='TRANSPORT_LOGISTICS';
