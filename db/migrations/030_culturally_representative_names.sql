-- Improve the cultural range of synthetic names without inferring gender from names.

CREATE TEMPORARY TABLE synthetic_name_updates (
    slot INT PRIMARY KEY,
    first_name VARCHAR(80) NOT NULL,
    middle_name VARCHAR(100) NULL,
    surname VARCHAR(80) NOT NULL
);

INSERT INTO synthetic_name_updates (slot,first_name,middle_name,surname) VALUES
    (0,'Zainab','Musa','Abubakar'),
    (2,'Aisha','Ibrahim','Bello'),
    (4,'Aishatu','Anisa','Lawal'),
    (6,'Yasmin','Fatima','Usman');

-- Update matching licence records first so they retain the same synthetic
-- identity details after the national identity record changes.
UPDATE licences l
JOIN citizens c ON c.full_name=l.holder_full_name AND c.date_of_birth=l.holder_date_of_birth
JOIN synthetic_name_updates n ON n.slot=MOD(c.citizen_id-1,32)
SET l.holder_first_name=n.first_name,
    l.holder_middle_name=n.middle_name,
    l.holder_surname=n.surname,
    l.holder_full_name=CONCAT_WS(' ',n.first_name,n.middle_name,n.surname);

UPDATE citizens c
JOIN synthetic_name_updates n ON n.slot=MOD(c.citizen_id-1,32)
SET c.first_name=n.first_name,
    c.middle_name=n.middle_name,
    c.surname=n.surname,
    c.full_name=CONCAT_WS(' ',n.first_name,n.middle_name,n.surname);

-- Apply the same profiles to licence-only records according to their stable slot.
UPDATE licences l
LEFT JOIN citizens c ON c.full_name=l.holder_full_name AND c.date_of_birth=l.holder_date_of_birth
JOIN synthetic_name_updates n ON n.slot=MOD(l.licence_record_id-1,32)
SET l.holder_first_name=n.first_name,
    l.holder_middle_name=n.middle_name,
    l.holder_surname=n.surname,
    l.holder_full_name=CONCAT_WS(' ',n.first_name,n.middle_name,n.surname)
WHERE c.citizen_id IS NULL;

DROP TEMPORARY TABLE synthetic_name_updates;
