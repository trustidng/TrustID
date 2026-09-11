# Architecture Amendment 002 — Independent Authorities and Identity Photographs

## Status

Implemented after Phase 7. This amendment supersedes the earlier synthetic
licence-to-citizen foreign-key model without changing or re-signing historical
receipts.

## Independent trusted sources

The Synthetic National Identity Authority and Synthetic Driver Licensing
Authority are independent. A licence record no longer contains a foreign key
to a national identity record. The licence authority holds its own stable
record ID, holder name, date of birth, photograph reference, licence details,
record status, and timestamps.

Some fictional records deliberately share the same name, date of birth, and
photograph across both sources to represent the same synthetic person. This is
seed-data coordination only; no database relationship claims that the records
belong to the same person. Other national identity holders have no licence and
some licence holders exist only in the licence authority.

Every verification records its internal `subject_authority` and
`source_record_id`. Licence verifications may have no TrustID `citizen_id`.
Organization-facing subject references are organization scoped and authority
domain separated. Existing national-identity pseudonyms retain their original
derivation so historical continuity is preserved.

## Identity photograph response

Every successful person-linked verification may temporarily show
the trusted source's identity photograph to the authenticated requesting
organization. The interface instructs the organization to compare it with the
person presenting the identity or the applicant's current photograph. TrustID
does not claim that it performed this comparison.

The photograph:

- is disclosed before submission as part of the information returned;
- appears only after a permitted request produces a successful result;
- is retrieved through an authenticated, organization-scoped endpoint;
- is protected by rate limiting, anti-probing behavior, auditing, and
  `Cache-Control: no-store`;
- is never copied into verification, history, receipt, QR, or public-result
  data; and
- is never placed in the public static directory.

The local asset is a set of fictional AI-generated portraits. Reuse across
synthetic records is deliberate demo behavior and is not a production data
model.

## Freshness amendment

Both driving-licence status and driving-licence class results are current for
24 hours. Age requirements are current for 24 hours and identity-record confirmation for 30
days. Expiry does not invalidate a signature; it requires a new authoritative
verification before relying on the result.

## Signing information

Organization receipts show only the understandable live authenticity state.
Administrative oversight may show the algorithm, signing-key reference, key
status, and verified receipt status. Raw signatures, public-key material,
canonical payloads, private keys, and share tokens remain outside normal user
interfaces.
