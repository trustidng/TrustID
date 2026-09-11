# TrustID administrative governance

TrustID supports multiple administrator accounts with two roles:

- **Primary administrator** manages administrator accounts in addition to the normal organization and category controls.
- **Administrator** manages organization lifecycle, categories, permissions, and privacy-safe operational oversight.

Primary administrators can create accounts, change roles, reset passwords,
deactivate accounts, and restore access. New and reset passwords are temporary;
the account holder must replace them at the next sign-in. Deactivation revokes
all active sessions immediately. TrustID prevents self-deactivation and prevents
removing or demoting the final active primary administrator.

Every account-management action is written to the audit log. Passwords and
temporary passwords are never included in audit details.

## Organization verification oversight

Administrators can open **View verification history** from an organization card.
The newest requests appear first and show only the operational contract needed
for oversight: public verification reference, pseudonymous subject reference,
verification type, plain-language requirement, purpose, outcome, timestamps,
citizen-approval status, and notification delivery status where applicable.

The view never queries or displays raw NINs, driving-licence numbers, telephone
numbers, dates of birth, exact ages, or protected attribute values. Opening an
organization's verification history creates an audit event containing only the
organization identifier and number of records viewed.
