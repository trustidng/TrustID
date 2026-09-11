-- Preserve legacy organization-creation paths. The signing transaction assigns
-- and locks a stable reference before the organization's first signed receipt.
ALTER TABLE organisations MODIFY COLUMN public_reference VARCHAR(20) NULL;
