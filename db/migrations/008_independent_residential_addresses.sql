-- Correct the first address backfill: residence location is independent of
-- state of origin. The deterministic formula keeps demo resets reproducible.
UPDATE citizens
SET residential_address = CONCAT(
    1 + MOD(citizen_id * 17, 199), ' ',
    ELT(1 + MOD(citizen_id * 11, 10),
        'Unity Road', 'Independence Avenue', 'Community Close', 'Market Road',
        'College Estate', 'New Layout', 'Peace Crescent', 'Station Road',
        'Government Reservation Area', 'Garden Close'),
    ', ',
    ELT(1 + MOD(citizen_id * 13 + 5, 37),
        'Abia', 'Adamawa', 'Akwa Ibom', 'Anambra', 'Bauchi', 'Bayelsa', 'Benue',
        'Borno', 'Cross River', 'Delta', 'Ebonyi', 'Edo', 'Ekiti', 'Enugu',
        'FCT - Abuja', 'Gombe', 'Imo', 'Jigawa', 'Kaduna', 'Kano', 'Katsina',
        'Kebbi', 'Kogi', 'Kwara', 'Lagos', 'Nasarawa', 'Niger', 'Ogun', 'Ondo',
        'Osun', 'Oyo', 'Plateau', 'Rivers', 'Sokoto', 'Taraba', 'Yobe', 'Zamfara')
);
