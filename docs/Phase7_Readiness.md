# TrustID Phase 7 — Privacy-Safe Verification Receipts Readiness

## Status

This document records the implemented and verified Phase 7 contract. Phase 6
was the verified entry state: completed instant
results already receive one Ed25519-signed receipt, QR code, shareable
authenticity URL, and live current/expired/invalid classification.

## Goal

Phase 7 gives an organization a useful, professional record proving that a
verification happened without turning TrustID into a second identity database.
It answers:

> What was verified, what was the outcome, when was it true, when did it stop
> being current, and can TrustID still authenticate the proof?

The receipt proves a verification event. It is not a copy of the citizen's
identity record and it is not a permanent credential.

## Phase boundary

Phase 6 owns signing, canonicalization, key handling, QR generation, and
authenticity validation. Phase 7 reuses those services and adds the receipt
history, detail, print/share, status, and oversight experience.

Phase 7 must not:

- create a second receipt table;
- change the frozen signed payload;
- re-sign a result merely because somebody views or prints it;
- create receipts for pending, denied, failed, or unavailable requests;
- sign or disclose direct personal attributes before Phase 8 approval; or
- merge verifier-facing receipts with the internal `audit_log`.

## Reconciliation of purpose

The older build-plan summary lists purpose as a receipt field, while the later
Phase 0 receipt schema and fixed signed payload omit it. The fixed Phase 0
contract wins.

The organization receipt screen may show the already validated verification
purpose joined from `verifications`. Purpose is not copied
into `receipts`, added to `canonical_payload`, or described as digitally
signed. The printable receipt separates it under **Verification purpose** from the
**Digitally signed result** section.

## Receipt data contract

The signed proof contains only:

- verification/transaction reference;
- claim code;
- normalized condition;
- Boolean result;
- issued time;
- expiry time;
- stable public organization reference;
- organization-scoped subject reference;
- exact canonical payload;
- Ed25519 signature;
- signing key identifier and algorithm; and
- public authenticity token.

The authenticated organization view may join safe display metadata:

- professional verification label;
- plain-language requirement and outcome;
- validated request purpose, clearly separated from the signed proof; and
- live integrity/freshness status.

It must never expose or persist in the receipt:

- NIN or licence number;
- internal citizen ID;
- date of birth or calculated exact age;
- phone number;
- legal name, state of origin, or residential address;
- full trusted-source data;
- PIN, OTP, session data, private keys, or provider payloads; or
- unrestricted audit-log details.

## Receipt lifecycle

1. A permitted instant verification completes.
2. Phase 6 creates one signed receipt atomically with the result.
3. Phase 7 lists the receipt for the requesting organization.
4. Viewing, printing, or sharing does not create another receipt.
5. Authenticity and expiry are recalculated whenever the receipt is opened.
6. Expiry changes the display state, not the signed data.
7. An expired receipt remains in history as evidence that a check occurred.
8. A revoked or invalid signature remains visible only as an integrity warning;
   its result must not be presented as trustworthy.

Existing completed Phase 5 results without receipts remain labelled **Created
before digital signing was enabled**. Phase 7 does not silently backfill them.

## Organization receipt centre

Add an authenticated route such as:

```text
GET /organisation/receipts
```

The organization dashboard gains a clear **Verification receipts** action and
a signed-receipt count. The receipt centre is newest first and uses bounded,
server-side pagination.

Each row shows:

- verification reference;
- verification type;
- plain-language requirement;
- **Requirement met** or **Requirement not met**;
- **Authentic and current**, **Authentic but expired**, or **Integrity issue**;
- issued time and valid-until time; and
- **View receipt**.

Useful filters:

- all receipts;
- current;
- expired;
- integrity issue;
- verification type; and
- an optional bounded date range.

Filters are allowlisted server-side and must not become arbitrary SQL, expose
another organization's counts, or accept raw citizen identifiers.

Empty state:

> No signed verification receipts yet. Completed verifications will appear
> here automatically.

## Authenticated receipt detail

Add an organization-isolated route such as:

```text
GET /organisation/receipts/{transaction_id}
```

Every lookup includes the authenticated `organisation_id`. Guessing another
organization's transaction reference returns the same safe not-found behavior
as an unknown reference.

The page contains:

### Result

- professional verification name;
- plain-language requirement;
- **Requirement met** or **Requirement not met**; and
- current authenticity/freshness badge.

### Digitally signed proof

- verification reference;
- public organization reference;
- pseudonymous subject reference;
- issued time;
- valid-until time;
- QR code;
- **Verify authenticity**; and
- **Copy verification link**.

### Verification purpose

- the validated purpose provided for the verification request.

The organization experience does not show raw signatures, canonical JSON,
public keys, algorithms, or key identifiers. Limited signing information is
available only in authenticated administrator oversight.

## Print and sharing experience

The core MVP uses a print-friendly HTML receipt rather than introducing PDF
generation risk. Provide **Print or save receipt** using a dedicated print
stylesheet that:

- retains the QR code and important status;
- removes navigation, buttons, and unrelated dashboard content;
- prints the verification URL as readable text;
- includes issue and expiry times with timezone labels;
- clearly marks an expired or invalid receipt; and
- never prints hidden technical or personal data.

The link field should not dominate the page. Prefer **Copy verification link**
with an accessible success message, while keeping the URL available for users
who need to copy it manually.

A server-generated PDF is an optional enhancement only after the HTML/print
flow is complete, privacy-tested, and visually verified. If added, it must be
generated from an explicit receipt view model—not by capturing an authenticated
page or database row.

## Public authenticity page relationship

Continue using the Phase 6 public page. A public recipient sees only the
limited signed result, never the organization-only purpose or account history.
The four states remain:

- **Authentic and current**;
- **Authentic but expired**;
- **Invalid or altered**; and
- **Result unavailable**.

The public token is deliberately shareable and high entropy. It is not used as
an organization-session credential. The existing global privacy-safe rate
limit and `noindex` response remain mandatory.

## Time and freshness presentation

Canonical timestamps remain UTC `Z` values and must never be reformatted before
signature checking. User-facing pages display an unambiguous local time such
as **1 Sep 2026, 2:15 PM WAT**, while preserving the exact signed UTC value
internally.

Freshness remains:

| Verification | Current for |
|---|---:|
| Age requirement | 24 hours |
| Driving licence status | 24 hours |
| Identity status | 30 days |
| Driving licence class | 24 hours |

The interface must explain that expiry means a new authoritative check is
required. It does not mean the previous signature became invalid.

## Administrator oversight

The existing privacy-safe organization history may show whether a completed
verification has a receipt and its live integrity/freshness status.
Administrators do not receive raw identifiers, protected attributes, canonical
payloads, signatures, private keys, or unrestricted public tokens.

Administrative oversight remains distinct from the organization receipt
centre. It supports investigation; it does not let an administrator impersonate
the organization or silently share its receipt.

## Database and query work

Reuse `receipts`, `verifications`, `organisations`, and `signing_keys`.
Before adding a migration, inspect actual query plans and existing indexes.
Likely Phase 7 additions are limited to:

- an index supporting organization receipt history ordered by `issued_at`;
- an audit event enum only if authenticated receipt viewing is deliberately
  audited; and
- no new personal-data or duplicate receipt columns.

`integrity_status` is never trusted as authoritative. Live verification of the
exact canonical payload and signature determines the displayed state.

Receipt retention is separate from result freshness. For the MVP, expired
receipts remain available as historical proof. Production retention/deletion
policy should be documented later rather than inferred from `expires_at`.

## Privacy and security controls

- Every organization list/detail query is scoped by authenticated organization.
- Public pages are accessible only through the unguessable share token.
- Receipt HTML, print output, QR content, URLs, logs, and audit detail receive
  explicit forbidden-field tests.
- Canonical payloads are never parsed into an unrestricted template context.
- Invalid receipts do not render their untrusted payload values.
- Purpose is escaped and remains governed by the Phase 5 validation rules.
- Copy/share controls never put session or CSRF tokens into URLs.
- Responses retain `Cache-Control: no-store`, restrictive CSP, frame denial,
  referrer protection, and public-page search-engine exclusion.
- Receipt endpoints must not call a trusted identity/licensing source; they
  display an already completed proof only.

## UI and accessibility improvements

- Use **Verification receipt**, not “audit object” or cryptographic jargon.
- Use one dominant status, with colour plus text/icon rather than colour alone.
- Make QR codes large enough for phone scanning and provide a text alternative.
- Keep action order simple: **Verify authenticity**, **Copy link**, **Print or
  save**.
- Provide copy-success feedback without requiring a page reload.
- Ensure keyboard focus, screen-reader labels, mobile stacking, print contrast,
  and long-reference wrapping.
- Show a warning banner—not a normal success layout—for expired or invalid
  receipts.
- Keep purpose visibly separate so users do not assume TrustID signed or proved
  the organization's stated reason.

## Optional improvements after the core

These are useful but not Phase 7 blockers:

- revoke and regenerate a public sharing link without changing the receipt or
  signature;
- downloadable PDF generated from an allowlisted receipt view model;
- receipt CSV export containing only privacy-safe summary fields;
- organization-configurable receipt retention subject to a platform minimum;
  and
- richer accessibility/usability testing with external participants.

Emailing receipts directly is not required. TrustID should provide a safe link;
the organization chooses its communication channel.

## Required tests

Add unit, route, privacy, database, and rendered-page coverage for:

- organization receipt list, pagination, filters, and empty state;
- organization-scoped receipt detail and cross-organization guessing;
- live current, expired, invalid, and revoked-key states;
- signed receipt versus unsigned historical result;
- no receipt for pending consent, denied, or failed verification;
- one receipt per completed verification despite retries;
- purpose shown only as contextual, escaped, and absent from canonical payload;
- exact 24-hour and 30-day freshness behavior;
- UTC signature values and clear WAT presentation;
- QR/link continuity with the Phase 6 public page;
- copy-link and print layout behavior;
- absence of forbidden personal fields in receipt HTML, print output, QR URL,
  database receipt rows, and audit details;
- administrator oversight remaining privacy-safe;
- receipt routes performing no trusted-source lookup; and
- all Phase 2–6 and administration-governance regressions.

Add `scripts/verify_phase7.py`. Its database-backed acceptance flow should:

1. create completed signed receipts for one organization;
2. create a second organization;
3. confirm list/detail visibility and cross-organization isolation;
4. confirm current and expired display states;
5. confirm purpose separation and privacy-safe HTML/print output;
6. confirm QR/public authenticity continuity;
7. confirm pending requests produce no receipt;
8. confirm retries do not duplicate receipts; and
9. clean up every temporary record.

## Implementation order

1. Freeze this contract and inspect the current receipt queries/indexes.
2. Add only the minimal forward-only migration justified by query/audit needs.
3. Build a single privacy-safe receipt view-model/service using Phase 6
   verification rather than duplicating cryptographic logic.
4. Add organization receipt list, filters, pagination, and dashboard entry.
5. Add organization-isolated receipt detail and live status presentation.
6. Add copy-link behavior and print stylesheet.
7. Extend privacy-safe administrator oversight without exposing share secrets.
8. Add Phase 7 tests and database acceptance script.
9. Inspect desktop, mobile, print, current, expired, invalid, empty, and
   cross-organization states.
10. Run migrations, the full automated suite, admin governance, and Phase 2–7
    acceptance scripts.

## Completion criteria

Phase 7 is complete only when organizations can find, understand, verify,
share, and print their own signed receipts; expiry and integrity are calculated
live and explained correctly; purpose is clearly separated from the signed
proof; cross-organization access fails safely; administrators retain
privacy-safe oversight; no personal identity values leak; the Phase 7
acceptance script passes; and every earlier regression gate remains green.

## Implementation verification

Phase 7 is complete. The organization portal now has one **Verification
history** centre with **All requests** and **Verification receipts** views,
reference/status/type/date filters, bounded pages, responsive tables, and clear
empty states. Signed results open in a dedicated organization-isolated receipt
page with live authenticity status, QR verification, copy actions, WAT times,
request-context separation, related-verification navigation, and print/save
styling. The dashboard shows the five latest requests and direct history and
receipt entry points.

The forward-only `017_phase7_receipt_history.sql` migration adds only the
organization/time query index. `scripts/verify_phase7.py` validates 500-record
history behavior, filtering, current/expired/integrity states, cross-
organization isolation, pending-without-receipt behavior, privacy-safe HTML,
and cleanup. Phase 2–6, administration governance, and the full automated test
suite remain required regression gates.
