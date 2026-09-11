-- Deterministic Nigerian names for the current synthetic dataset. Matching
-- licence details are updated first; boundary-test names remain stable.

CREATE TEMPORARY TABLE synthetic_name_map (
    slot INT PRIMARY KEY,
    full_name VARCHAR(150) NOT NULL
);

INSERT INTO synthetic_name_map (slot,full_name) VALUES
    (0,'Aisha Bello'),(1,'Musa Abdullahi'),(2,'Fatima Garba'),(3,'Ibrahim Suleiman'),
    (4,'Zainab Lawal'),(5,'Sani Danladi'),(6,'Hauwa Usman'),(7,'Bashir Adamu'),
    (8,'Chiamaka Okafor'),(9,'Chinedu Nwosu'),(10,'Adaeze Eze'),(11,'Obinna Onyeka'),
    (12,'Ngozi Umeh'),(13,'Ifeanyi Obi'),(14,'Amarachi Nnamani'),(15,'Kelechi Ibekwe'),
    (16,'Temilade Adebayo'),(17,'Adewale Ogunleye'),(18,'Yetunde Balogun'),(19,'Oluwaseun Adeyemi'),
    (20,'Ayomide Fashola'),(21,'Babatunde Oladipo'),(22,'Bisola Akinyemi'),(23,'Femi Ajayi'),
    (24,'Iniobong Okon'),(25,'Aniefiok Essien'),(26,'Mfon Etim'),(27,'Imaobong Ekanem'),
    (28,'Terna Iorfa'),(29,'Dooshima Ortom'),(30,'Tari Briggs'),(31,'Osaze Omoregie');

UPDATE licences l
JOIN citizens c ON c.full_name=l.holder_full_name AND c.date_of_birth=l.holder_date_of_birth
JOIN synthetic_name_map n ON n.slot=MOD(c.citizen_id-1,32)
SET l.holder_full_name=n.full_name
WHERE c.full_name NOT IN ('Exactly Eighteen Test','Exactly Thirty Test');

UPDATE citizens c
JOIN synthetic_name_map n ON n.slot=MOD(c.citizen_id-1,32)
SET c.full_name=n.full_name
WHERE c.full_name NOT IN ('Exactly Eighteen Test','Exactly Thirty Test');

DROP TEMPORARY TABLE synthetic_name_map;
