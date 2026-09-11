-- Present NIN verification as one authoritative record-confirmation check.
-- The stable claim code is retained so existing permissions and signed receipts
-- remain valid.
UPDATE claim_definitions
SET display_name = 'Verify identity record'
WHERE claim_code = 'IDENTITY_STATUS';
