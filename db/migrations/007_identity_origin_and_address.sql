-- Preserve the existing synthetic state values as state of origin, then add a
-- separate fictional residential address for every synthetic citizen.
ALTER TABLE citizens
    CHANGE COLUMN state_of_residence state_of_origin VARCHAR(50) NOT NULL,
    ADD COLUMN residential_address VARCHAR(255) NULL AFTER state_of_origin;

UPDATE citizens
SET residential_address = CONCAT(
    1 + MOD(citizen_id * 17, 199), ' ',
    ELT(1 + MOD(citizen_id, 10),
        'Unity Road', 'Independence Avenue', 'Community Close', 'Market Road',
        'College Estate', 'New Layout', 'Peace Crescent', 'Station Road',
        'Government Reservation Area', 'Garden Close'),
    ', ', state_of_origin
)
WHERE residential_address IS NULL;

ALTER TABLE citizens
    MODIFY COLUMN residential_address VARCHAR(255) NOT NULL;
