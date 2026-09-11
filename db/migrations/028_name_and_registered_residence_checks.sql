-- Structured identity names and privacy-preserving match verifications.

ALTER TABLE citizens
    ADD COLUMN surname VARCHAR(80) NULL AFTER full_name,
    ADD COLUMN first_name VARCHAR(80) NULL AFTER surname,
    ADD COLUMN middle_name VARCHAR(100) NULL AFTER first_name,
    ADD COLUMN state_of_residence VARCHAR(50) NULL AFTER state_of_origin,
    ADD COLUMN lga_of_residence VARCHAR(80) NULL AFTER state_of_residence;

UPDATE citizens
SET first_name=SUBSTRING_INDEX(full_name,' ',1),
    surname=SUBSTRING_INDEX(full_name,' ',-1),
    middle_name=NULLIF(TRIM(SUBSTRING(
        full_name,
        LENGTH(SUBSTRING_INDEX(full_name,' ',1))+2,
        LENGTH(full_name)-LENGTH(SUBSTRING_INDEX(full_name,' ',1))-LENGTH(SUBSTRING_INDEX(full_name,' ',-1))-2
    )),''),
    state_of_residence=TRIM(SUBSTRING_INDEX(residential_address,',',-1));

UPDATE citizens
SET lga_of_residence = CASE state_of_residence
    WHEN 'Abia' THEN 'Umuahia North' WHEN 'Adamawa' THEN 'Yola North'
    WHEN 'Akwa Ibom' THEN 'Uyo' WHEN 'Anambra' THEN 'Awka South'
    WHEN 'Bauchi' THEN 'Bauchi' WHEN 'Bayelsa' THEN 'Yenagoa'
    WHEN 'Benue' THEN 'Makurdi' WHEN 'Borno' THEN 'Maiduguri'
    WHEN 'Cross River' THEN 'Calabar Municipal' WHEN 'Delta' THEN 'Oshimili South'
    WHEN 'Ebonyi' THEN 'Abakaliki' WHEN 'Edo' THEN 'Oredo'
    WHEN 'Ekiti' THEN 'Ado Ekiti' WHEN 'Enugu' THEN 'Enugu North'
    WHEN 'FCT - Abuja' THEN 'Abuja Municipal' WHEN 'Gombe' THEN 'Gombe'
    WHEN 'Imo' THEN 'Owerri Municipal' WHEN 'Jigawa' THEN 'Dutse'
    WHEN 'Kaduna' THEN 'Kaduna North' WHEN 'Kano' THEN 'Kano Municipal'
    WHEN 'Katsina' THEN 'Katsina' WHEN 'Kebbi' THEN 'Birnin Kebbi'
    WHEN 'Kogi' THEN 'Lokoja' WHEN 'Kwara' THEN 'Ilorin West'
    WHEN 'Lagos' THEN 'Ikeja' WHEN 'Nasarawa' THEN 'Lafia'
    WHEN 'Niger' THEN 'Chanchaga' WHEN 'Ogun' THEN 'Abeokuta South'
    WHEN 'Ondo' THEN 'Akure South' WHEN 'Osun' THEN 'Osogbo'
    WHEN 'Oyo' THEN 'Ibadan North' WHEN 'Plateau' THEN 'Jos North'
    WHEN 'Rivers' THEN 'Port Harcourt' WHEN 'Sokoto' THEN 'Sokoto North'
    WHEN 'Taraba' THEN 'Jalingo' WHEN 'Yobe' THEN 'Damaturu'
    WHEN 'Zamfara' THEN 'Gusau' ELSE 'Not specified' END;

ALTER TABLE citizens
    MODIFY COLUMN surname VARCHAR(80) NOT NULL,
    MODIFY COLUMN first_name VARCHAR(80) NOT NULL,
    MODIFY COLUMN state_of_residence VARCHAR(50) NOT NULL,
    MODIFY COLUMN lga_of_residence VARCHAR(80) NOT NULL;

ALTER TABLE licences
    ADD COLUMN holder_surname VARCHAR(80) NULL AFTER holder_full_name,
    ADD COLUMN holder_first_name VARCHAR(80) NULL AFTER holder_surname,
    ADD COLUMN holder_middle_name VARCHAR(100) NULL AFTER holder_first_name;

UPDATE licences
SET holder_first_name=SUBSTRING_INDEX(holder_full_name,' ',1),
    holder_surname=SUBSTRING_INDEX(holder_full_name,' ',-1),
    holder_middle_name=NULLIF(TRIM(SUBSTRING(
        holder_full_name,
        LENGTH(SUBSTRING_INDEX(holder_full_name,' ',1))+2,
        LENGTH(holder_full_name)-LENGTH(SUBSTRING_INDEX(holder_full_name,' ',1))-LENGTH(SUBSTRING_INDEX(holder_full_name,' ',-1))-2
    )), '');

ALTER TABLE licences
    MODIFY COLUMN holder_surname VARCHAR(80) NOT NULL,
    MODIFY COLUMN holder_first_name VARCHAR(80) NOT NULL;

INSERT INTO claim_definitions (claim_code,display_name,action_type,privacy_mode) VALUES
    ('NAME_MATCH','Verify name match','VERIFY','INSTANT'),
    ('REGISTERED_RESIDENCE','Verify registered residence','VERIFY','STRONG_CONSENT');

INSERT INTO category_claim_permissions (category_id,claim_code)
SELECT c.id,p.claim_code FROM organisation_categories c JOIN (
    SELECT 'PROGRAMME_OPERATOR' code,'NAME_MATCH' claim_code UNION ALL
    SELECT 'PROGRAMME_OPERATOR','REGISTERED_RESIDENCE' UNION ALL
    SELECT 'GOVERNMENT','NAME_MATCH' UNION ALL
    SELECT 'GOVERNMENT','REGISTERED_RESIDENCE' UNION ALL
    SELECT 'FINANCIAL','NAME_MATCH' UNION ALL
    SELECT 'FINANCIAL','REGISTERED_RESIDENCE' UNION ALL
    SELECT 'TRANSPORT_LOGISTICS','NAME_MATCH'
) p ON p.code=c.code;

CREATE TABLE consent_request_contexts (
    consent_request_id INT PRIMARY KEY,
    ciphertext BLOB NOT NULL,
    nonce BINARY(12) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (consent_request_id) REFERENCES consent_requests(id) ON DELETE CASCADE
) ENGINE=InnoDB;
