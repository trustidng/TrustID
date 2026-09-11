-- Independent USSD availability control. Status changes use the attributed audit log.
ALTER TABLE service_status
    MODIFY COLUMN service_code ENUM('NATIONAL_ID','DRIVING_LICENCE','SMS','USSD') NOT NULL;
INSERT INTO service_status (service_code,display_name) VALUES ('USSD','USSD service');
