-- Consistent synthetic names, authority-provided gender and portrait assignment.

ALTER TABLE citizens
    ADD COLUMN gender ENUM('MALE','FEMALE') NULL AFTER date_of_birth;

ALTER TABLE licences
    ADD COLUMN holder_gender ENUM('MALE','FEMALE') NULL AFTER holder_date_of_birth;

CREATE TEMPORARY TABLE synthetic_identity_map (
    slot INT PRIMARY KEY,
    first_name VARCHAR(80) NOT NULL,
    middle_name VARCHAR(100) NULL,
    surname VARCHAR(80) NOT NULL,
    gender ENUM('MALE','FEMALE') NOT NULL
);

INSERT INTO synthetic_identity_map (slot,first_name,middle_name,surname,gender) VALUES
    (0,'Aisha','Zainab','Bello','FEMALE'),(1,'Musa','Sani','Abdullahi','MALE'),
    (2,'Fatima','Amina','Garba','FEMALE'),(3,'Ibrahim','Sadiq','Suleiman','MALE'),
    (4,'Zainab',NULL,'Lawal','FEMALE'),(5,'Sani','Musa','Danladi','MALE'),
    (6,'Hauwa','Fatima','Usman','FEMALE'),(7,'Bashir',NULL,'Adamu','MALE'),
    (8,'Chiamaka','Adaeze','Okafor','FEMALE'),(9,'Chinedu','Emeka','Nwosu','MALE'),
    (10,'Adaeze','Ngozi','Eze','FEMALE'),(11,'Obinna','Chukwuemeka','Onyeka','MALE'),
    (12,'Ngozi',NULL,'Umeh','FEMALE'),(13,'Ifeanyi','Chibuzo','Obi','MALE'),
    (14,'Amarachi','Chioma','Nnamani','FEMALE'),(15,'Kelechi',NULL,'Ibekwe','MALE'),
    (16,'Temilade','Abiola','Adebayo','FEMALE'),(17,'Adewale','Babatunde','Ogunleye','MALE'),
    (18,'Yetunde',NULL,'Balogun','FEMALE'),(19,'Oluwaseun','Adekunle','Adeyemi','MALE'),
    (20,'Ayomide','Tolulope','Fashola','FEMALE'),(21,'Babatunde','Olumide','Oladipo','MALE'),
    (22,'Bisola','Temitope','Akinyemi','FEMALE'),(23,'Femi',NULL,'Ajayi','MALE'),
    (24,'Iniobong','Mfon','Okon','FEMALE'),(25,'Aniefiok','Udo','Essien','MALE'),
    (26,'Mfon',NULL,'Etim','FEMALE'),(27,'Imaobong','Eno','Ekanem','FEMALE'),
    (28,'Terna','Terseer','Iorfa','MALE'),(29,'Dooshima','Mngohol','Ortom','FEMALE'),
    (30,'Tari','Preye','Briggs','MALE'),(31,'Osaze',NULL,'Omoregie','MALE');

-- First update licence-only records while their current names can still be used
-- to distinguish them from records copied from the national identity source.
UPDATE licences l
LEFT JOIN citizens c ON c.full_name=l.holder_full_name AND c.date_of_birth=l.holder_date_of_birth
JOIN synthetic_identity_map n ON n.slot=MOD(l.licence_record_id-1,32)
SET l.holder_first_name=n.first_name,
    l.holder_middle_name=n.middle_name,
    l.holder_surname=n.surname,
    l.holder_full_name=CONCAT_WS(' ',n.first_name,n.middle_name,n.surname),
    l.holder_gender=n.gender,
    l.holder_photograph_reference=CASE n.gender
        WHEN 'MALE' THEN ELT(1+MOD(l.licence_record_id-1,8),'PHOTO-0001','PHOTO-0003','PHOTO-0006','PHOTO-0008','PHOTO-0009','PHOTO-0011','PHOTO-0014','PHOTO-0016')
        ELSE ELT(1+MOD(l.licence_record_id-1,8),'PHOTO-0002','PHOTO-0004','PHOTO-0005','PHOTO-0007','PHOTO-0010','PHOTO-0012','PHOTO-0013','PHOTO-0015') END
WHERE c.citizen_id IS NULL;

-- Licence records representing the same synthetic person retain exactly the
-- same name, date of birth, gender and photograph as that identity record.
UPDATE licences l
JOIN citizens c ON c.full_name=l.holder_full_name AND c.date_of_birth=l.holder_date_of_birth
JOIN synthetic_identity_map n ON n.slot=MOD(c.citizen_id-1,32)
SET l.holder_first_name=n.first_name,
    l.holder_middle_name=n.middle_name,
    l.holder_surname=n.surname,
    l.holder_full_name=CONCAT_WS(' ',n.first_name,n.middle_name,n.surname),
    l.holder_gender=n.gender,
    l.holder_photograph_reference=CASE n.gender
        WHEN 'MALE' THEN ELT(1+MOD(c.citizen_id-1,8),'PHOTO-0001','PHOTO-0003','PHOTO-0006','PHOTO-0008','PHOTO-0009','PHOTO-0011','PHOTO-0014','PHOTO-0016')
        ELSE ELT(1+MOD(c.citizen_id-1,8),'PHOTO-0002','PHOTO-0004','PHOTO-0005','PHOTO-0007','PHOTO-0010','PHOTO-0012','PHOTO-0013','PHOTO-0015') END;

UPDATE citizens c
JOIN synthetic_identity_map n ON n.slot=MOD(c.citizen_id-1,32)
SET c.first_name=n.first_name,
    c.middle_name=n.middle_name,
    c.surname=n.surname,
    c.full_name=CONCAT_WS(' ',n.first_name,n.middle_name,n.surname),
    c.gender=n.gender,
    c.identity_photograph_reference=CASE n.gender
        WHEN 'MALE' THEN ELT(1+MOD(c.citizen_id-1,8),'PHOTO-0001','PHOTO-0003','PHOTO-0006','PHOTO-0008','PHOTO-0009','PHOTO-0011','PHOTO-0014','PHOTO-0016')
        ELSE ELT(1+MOD(c.citizen_id-1,8),'PHOTO-0002','PHOTO-0004','PHOTO-0005','PHOTO-0007','PHOTO-0010','PHOTO-0012','PHOTO-0013','PHOTO-0015') END;

ALTER TABLE citizens MODIFY COLUMN gender ENUM('MALE','FEMALE') NOT NULL;
ALTER TABLE licences MODIFY COLUMN holder_gender ENUM('MALE','FEMALE') NOT NULL;

DROP TEMPORARY TABLE synthetic_identity_map;
