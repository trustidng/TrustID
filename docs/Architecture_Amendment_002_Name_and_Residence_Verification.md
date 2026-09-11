# Architecture Amendment 002: Name and Registered Residence Verification

## Decision

TrustID adds two limited-result verifications:

| Code | User-facing name | Result | Approval |
|---|---|---|---|
| `NAME_MATCH` | Verify name match | Name match confirmed / Name match not confirmed | Instant for permitted organizations |
| `REGISTERED_RESIDENCE` | Verify registered residence | Residence confirmed / Residence not confirmed | Citizen approval required |

`NAME_MATCH` accepts either an 11-digit NIN or a driving licence number. The
organization supplies surname, first name and an optional middle name. Matching
ignores capitalization, spacing, ordinary punctuation and diacritics, but does
not use broad fuzzy matching. The authoritative name is never returned.

`REGISTERED_RESIDENCE` accepts an NIN, a state and an optional LGA. The supplied
location is encrypted while approval is pending and deleted after approval,
decline or expiry. Neither the supplied location nor the trusted-source location
is included in the signed receipt. The result confirms the residence registered
with the identity source; it does not claim to prove physical presence today.

## Trusted-source structure

National identity records retain `full_name` for compatible display and add
`surname`, `first_name` and optional `middle_name`. Driving licence records add
equivalent `holder_*` fields and remain an independent authority.

National identity records also keep `state_of_origin` separate from
`state_of_residence`, `lga_of_residence` and `residential_address`.

## Default permissions

| Organization category | Name match | Registered residence |
|---|---:|---:|
| Retail | No | No |
| Programme operator | Yes | With citizen approval |
| Government | Yes | With citizen approval |
| Financial | Yes | With citizen approval |
| Transport and logistics | Yes | No |

Administrators may apply the same verification permissions to custom
organization categories. Public receipts contain only the generic condition and
binary result; names and locations remain outside receipt payloads and history.
