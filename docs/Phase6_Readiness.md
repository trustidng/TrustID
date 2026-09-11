# TrustID Phase 6 — Signing Service and Tamper Detection Readiness

## Status

This document records the implemented Phase 6 contract. Phase 5 and the
administration-hardening increment remain the verified entry state.

## Goal

Phase 6 makes every completed verification result tamper-evident. A recipient
can scan a QR code or open a verification link and independently learn whether
the result:

- was issued by TrustID and remains current;
- was issued by TrustID but has expired; or
- cannot be authenticated because it is unknown, malformed, or altered.

The QR code is a convenient link only. The Ed25519 signature is the proof.

## Source reconciliation

The canonical signing rules come from the original
`Phase0_Architecture_Freeze.md` and `TrustID_Build_Plan.md` retained in the
project owner's Downloads folder. Later implemented amendments supersede their
older identity-attribute and category descriptions: TrustID now models
`STATE_OF_ORIGIN` and `RESIDENTIAL_ADDRESS` independently and uses
database-driven categories. These amendments do not change the fixed signed
payload shape.

The two original source documents were not found in the expected user folders.
The reconciled signing contract below is therefore authoritative for Phase 6;
copies of the originals may be retained later as historical sources if found.

## Exact signed payload

Only this field set is signed:

```json
{
  "verification_id": "VR-2026-000184",
  "issuer": "TrustID",
  "claim": "AGE_COMPARE",
  "condition": "BETWEEN 18 AND 30",
  "result": "CONDITION_SATISFIED",
  "organisation_id": "ORG-0029",
  "subject_reference": "SUB-A81F2",
  "issued_at": "2026-08-28T03:45:12+01:00",
  "expires_at": "2026-08-29T03:45:12+01:00"
}
```

The fields have these fixed meanings:

- `verification_id` is the existing public `VR-...` verification reference;
- `issuer` is exactly `TrustID`;
- `claim` is the immutable claim code;
- `condition` is the normalized privacy-safe condition;
- `result` is `CONDITION_SATISFIED` or `CONDITION_NOT_SATISFIED`;
- `organisation_id` is a stable public `ORG-...` reference, never the internal
  numeric primary key;
- `subject_reference` is the organization-scoped HMAC pseudonym; and
- timestamps use RFC 3339 UTC (`YYYY-MM-DDTHH:MM:SSZ`) with second precision.

Purpose is deliberately excluded. It is operational context, may be corrected
or rendered differently, and is not part of the claim attestation.

The payload must never contain a NIN, licence number, phone number, internal
citizen ID, date of birth, exact age, name, origin, address, source record,
database row, HTML, session identifier, PIN, OTP, or private key material.

## Canonicalization

Construct the payload from an explicit allowlist and canonicalize it once with:

```python
json.dumps(payload, sort_keys=True, separators=(",", ":"))
```

Sign the UTF-8 bytes and store the exact canonical string. Verification checks
that stored string directly; it must not reconstruct JSON from database fields.
The canonical string must parse to an object containing exactly the frozen
field set and expected value types before its signature is accepted.

## Signing and transaction boundary

- Use Ed25519 from Python's `cryptography` package.
- Sign only completed instant results in Phase 6.
- Pending, denied, failed, or expired consent requests are not signed.
- Phase 8 signs a direct-disclosure result only after a valid citizen decision
  and controlled disclosure have produced a completed result.
- Result creation, canonicalization, signature generation, receipt insertion,
  and `RESULT_SIGNED` audit creation occur in the same database transaction.
- A signing failure must roll back the completed result rather than publish an
  unsigned result that appears final.
- One completed verification maps to exactly one receipt. Submission retries
  return the existing verification and receipt.

Existing Phase 5 results must not be silently presented as signed. The initial
Phase 6 implementation does not backfill them; they remain clearly labelled
**Created before digital signing was enabled**. A separately reviewed,
idempotent backfill may be added later using original issue and expiry times.

## Key handling and rotation

Private Ed25519 keys live outside the repository and database. Phase 6 uses:

- `TRUSTID_SIGNING_KEY_ID` — identifier of the active key;
- `TRUSTID_SIGNING_PRIVATE_KEY_B64` — base64-encoded private key supplied by
  the environment or an approved secret store; and
- a `signing_keys` table containing only key identifier, algorithm, public key,
  lifecycle status, activation time, retirement time, and creation time.

An explicit local setup command may generate a development key and print or
write environment-ready values to a gitignored location. Application startup
must never silently generate a replacement key. Startup validates that the
private key is well formed, derives its public key, and confirms that it matches
the active public-key record.

Key states are `ACTIVE`, `RETIRED`, and `REVOKED`, with exactly one active key.
Rotation activates one new signing key while retaining prior public keys for
verification. A retired key stops new signatures but its historical signatures
remain valid. A revoked, unknown, or mismatched key fails verification closed.
Key creation, activation, retirement, and revocation are audited without
recording private material.

## Receipt and migration contract

Reuse the existing `receipts` table; do not merge it with `audit_log` or create
a second receipt store. A forward-only Phase 6 migration should:

1. Add a unique, stable public reference such as `ORG-000029` to
   `organisations` and backfill existing rows deterministically.
2. Create `signing_keys` with no private-key column.
3. Add a unique, high-entropy `verification_token` to `receipts`. This is a
   deliberately shareable public lookup reference, not an authorization token.
4. Add `signing_key_id` and an algorithm constraint/reference to `receipts`.
5. Make `verification_id` unique so one verification has at most one receipt.
6. Retain the exact `canonical_payload`, signature, transaction/public
   reference, issue/expiry timestamps, organization link, and subject reference.
7. Add only the indexes needed for token lookup and organization history.

`integrity_status` must not be trusted as the source of truth. Current,
expired, or altered status is calculated from signature verification and the
signed expiry time on every authenticity check. If the existing column is
retained for compatibility, it is cached/display metadata only.

Signatures and public keys use a single documented base64 representation.
Database lengths must be bounded to their actual encoded sizes rather than
unlimited free-form text where practical.

## QR code and shareable verification link

Every completed signed result receives a QR code containing only an absolute
HTTPS URL of this form:

```text
https://trustid.example/verify-result/<high-entropy-token>
```

For local development the base URL may be `http://127.0.0.1:8000`, controlled
by a validated `PUBLIC_BASE_URL` setting. Production requires HTTPS and an
approved host. Never construct the QR host from an untrusted request `Host`
header.

The token must contain at least 256 bits of cryptographically secure randomness, be
unguessable, unique, URL-safe, and unrelated to the NIN, citizen ID,
organization ID, signature, or sequential database ID. QR generation is
server-side using a maintained library and is tested by decoding the generated
image back to the expected URL.

The QR code contains no payload or personal data. Anyone deliberately given
the QR/link can see the limited signed result, so the result page must disclose
only the canonical privacy-safe fields. It also uses `noindex`, strict
no-cache/no-referrer headers, and no third-party page resources.

## Authenticity endpoint

Add a read-only route:

```text
GET /verify-result/{token}
```

It performs this order:

1. Validate token format without revealing lookup details.
2. Load the receipt by its unique token.
3. Parse and structurally validate the exact canonical payload.
4. Load the referenced public key and confirm algorithm/key state.
5. Verify the Ed25519 signature over the stored canonical UTF-8 bytes.
6. Confirm immutable receipt columns agree with the signed payload.
7. Compare the signed `expires_at` with the current time.
8. Render one professional, privacy-safe state.

The public endpoint is rate-limited or otherwise protected against high-volume
enumeration. Unknown and malformed tokens share the same response and timing
class where practical. It never exposes stack traces or cryptographic errors.

## User experience

### Organization result page

Completed results show:

- **Digitally signed by TrustID**;
- **Requirement met** or **Requirement not met**;
- verification reference;
- verification type and requirement;
- pseudonymous subject reference;
- issued time and valid-until time;
- QR code;
- **Verify authenticity** button; and
- a copyable verification link/reference.

Cryptographic details are secondary and collapsed by default. Raw signatures
and public keys are not needed in the main experience. Pending consent requests
show no signature badge or QR code.

### Public authenticity page

Use four clear states:

- **Authentic and current** — issued by TrustID, unchanged, and within its
  freshness period.
- **Authentic but expired** — unchanged, but a new verification is required.
- **Invalid or altered** — integrity cannot be verified.
- **Result unavailable** — unknown, malformed, or unavailable reference.

The page explains that a signature proves who issued the result and whether it
changed; it does not claim that an expired fact remains true. It must work on
mobile after a QR scan, have strong contrast, keyboard accessibility, a text
alternative for the QR, and no sign-in requirement.

## Controlled tamper demonstration

Provide a development/acceptance-only tamper demonstration, never a public
database-edit feature. It should:

1. create a valid signed result;
2. verify **Authentic and current**;
3. alter a disposable copy of one signed field or canonical byte;
4. verify **Invalid or altered**; and
5. restore or delete all temporary data.

Also demonstrate an authentic expired result separately. Expiry is not
tampering and must never share the same message.

## Audit behavior

Create privacy-safe audit events for result signing and authenticity checks.
`RESULT_SIGNED` detail may contain only verification reference, claim code, and
key identifier. Verification-check audit or metrics must not record the public
token, full canonical payload, signature, IP address, user agent, raw
identifier, or protected citizen data. High-volume failures should be counted
without turning logs into a token oracle.

## Required tests

Unit and database-backed tests must cover:

- deterministic canonicalization and exact field allowlisting;
- Ed25519 sign/verify success;
- altered result, condition, subject, organization, issue time, and expiry time;
- signature substitution between receipts;
- unknown, malformed, retired, revoked, and mismatched keys;
- current versus authentic-expired versus invalid/altered states;
- fixed TTLs: 24 hours for age/licence status/licence class and 30 days for
  identity-record confirmation, as amended after Phase 7;
- receipt and submission idempotency;
- transaction rollback on signing failure;
- public-token uniqueness and non-sequential randomness;
- QR round-trip decoding to the configured public URL;
- absence of raw identifiers and protected values from payloads, receipts,
  URLs, HTML, audit details, and logs;
- organization-isolated receipt/history access;
- pending consent requests receiving no receipt or QR;
- mobile and desktop rendering of result/authenticity states; and
- all Phase 2–5 and administration-governance regressions.

Add `scripts/verify_phase6.py`. Its database-backed scenarios must include a
valid result, a tampered disposable result, an expired authentic result, QR
URL verification, privacy assertions, and cleanup.

## Implementation order

1. Reconcile/copy the architecture source documents and freeze this contract.
2. Add pinned `cryptography` and QR dependencies.
3. Add configuration validation and a safe development-key setup command.
4. Create the forward-only Phase 6 migration.
5. Implement canonical payload construction and signing as an isolated service.
6. Integrate signing atomically into completed verification creation.
7. Implement receipt lookup, signature validation, and state classification.
8. Add organization result QR/badge/link and the responsive public page.
9. Add the controlled tamper demonstration and Phase 6 acceptance script.
10. Run migration, unit/security tests, Phase 2–6 acceptance scripts, and
    rendered desktop/mobile checks.

## Completion criteria

Phase 6 is complete only when every eligible new completed result is signed,
the exact canonical string is retained, QR verification works, authentic,
expired, altered, and unavailable states are distinct, key rotation is
possible without losing historical verification, private keys remain outside
the repository/database, privacy assertions pass, and all existing regression
and new Phase 6 acceptance checks are green.

## Completion hardening

The final closure increment enforces the remaining readiness requirements:

- application lifespan validates the configured private key against the one
  active database public key before serving requests;
- organization registration assigns the stable public `ORG-...` reference;
- QR tests decode the generated image and compare the exact URL; and
- the public authenticity route uses a bounded, global MySQL minute bucket
  without retaining an IP address, token, or visitor identity. Only one
  privacy-safe rate-limit audit event is created per exceeded bucket.
