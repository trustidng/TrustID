# TrustID Phase 5 — Verifier Portal

## Implementation status

Phase 5 is implemented. The sections below are the enforced behavior and
acceptance contract, retained as the baseline for regression testing and the
Phase 8 consent handoff.

## Entry state

Phase 5 can build on these verified boundaries:

- organization authentication and approval/suspension lifecycle;
- database-driven active categories and claim permissions;
- professional, privacy-safe policy decisions and audit records;
- filtered verification options for approved organizations; and
- the internal Phase 3 predicate engine and trusted-source adapters.

The policy engine is the mandatory gateway. No portal route may call a Phase 3
adapter or engine before receiving `ALLOW_INSTANT` for that organization,
claim, and request attempt.

## Implemented Phase 5 behavior

### Guided organization journey

Use a short, claim-aware flow rather than one large form:

`Dashboard → Choose verification → Enter details → Review → Submit → Result or Awaiting approval`

The dashboard shows organization status, assigned category, available
verifications, pending requests, recent verifications, and a **New
verification** action only for approved organizations. The choice screen comes
first so the details screen can request only the identifier, condition, and
purpose appropriate to that claim.

The review screen repeats the claim, plain-language requirement, purpose, and
kind of information returned. It does not repeat the raw NIN or licence number;
show a masked reference only if it materially helps the user.

### Claim labels and professional language

The portal preserves the agreed distinction between a privacy-preserving check
and a request that may disclose a personal value:

| Claim | Organization-facing label |
|---|---|
| `AGE_COMPARE` | **Verify age requirement** |
| `IDENTITY_STATUS` | **Verify identity record** |
| `LICENCE_STATUS` | **Verify driving licence status** |
| `LICENCE_CLASS` | **Verify driving licence class** |
| `FULL_LEGAL_NAME` | **Request legal name** |
| `STATE_OF_ORIGIN` | **Request state of origin** |
| `RESIDENTIAL_ADDRESS` | **Request residential address** |

Direct-disclosure options carry **Citizen approval required**. Both consent
strengths use **The citizen's approval is required to continue**; the
organization never sees PIN, OTP, strong-consent, HMAC, predicate, inference,
or internal reason-code terminology. Pending, declined, expired, successful,
and unsuccessful states use the professional message catalogue in
`Architecture_Amendment_001_Identity_Attributes.md`.

### Request and policy boundary

- Add organization-only verifier routes and forms with CSRF protection.
- Render claim choices exclusively from `PolicyEngine.available_claims()`.
- Build condition inputs from the claim catalogue rather than accepting an
  arbitrary operator/value payload.
- Re-run `PolicyEngine.decide()` on submission even when the claim appeared in
  the rendered menu. Approval status, active category, and permission must be
  checked before any trusted-source access.
- After an allowed policy result, normalize and validate the citizen or licence
  reference while keeping failures non-enumerating. A raw identifier may be
  used transiently to resolve the subject, but must not enter persistent,
  history, receipt, or audit data.
- Invoke the Phase 3 engine only for `ALLOW_INSTANT`; stop on every denial.
- Protect submission with a one-time request reference backed by a database
  uniqueness constraint, so double-clicks cannot create duplicate
  verifications, consent messages, or probing-history entries.

### Purpose protection

Purpose is required. Server-side validation rejects obvious identifiers and
protected personal information before storing the text, without burdening the
interface with technical warning copy. Purpose must also have a practical
length limit and be safely rendered.

### Instant results and freshness

- Return only verifier-safe result contracts: organization-scoped subject
  reference, claim, plain-language condition, satisfied/not-satisfied result,
  `issued_at`, and `expires_at`.
- Do not show a date of birth, exact age, NIN, internal citizen ID, full source
  record, or raw database status.
- Produce freshness timestamps now even though Phase 6 adds signatures: 24
  hours for age, licence-status, and licence-class results, and 30 days for
  identity-status results (as amended after Phase 7).
- Use **Requirement met** and **Requirement not met** in the portal.

### Consent-required requests

- For `REQUIRE_CONSENT` and `REQUIRE_STRONG_CONSENT`, create both the pending
  verification and pending `consent_requests` record in Phase 5. In the same
  idempotent request-creation transaction, enqueue exactly one privacy-safe
  `CONSENT` SMS notification for the citizen's registered phone number.
- Add and populate `consent_requests.expires_at`; an expired approval cannot be
  reused and is shown as: **The approval request has expired. Please create a
  new verification request.**
- Show **Awaiting the citizen's approval** without exposing confirmation
  strength, channel, PIN/OTP mechanics, or the requested personal value.
- Do not query the trusted source or release legal name, state of origin, or
  residential address before the valid Phase 8 citizen decision.
- Preserve the Phase 8 handoff contract: web approval requires the TrustID PIN
  followed by an SMS OTP; web rejection requires the PIN; USSD approval and
  rejection require a trusted registered originating number plus the PIN, with
  no additional OTP. Phase 5 stores no simulated decision and does not expose
  the eventual confirmation channel to the organization.

### Consent notification and centralized phone inbox

The Phase 5 SMS tells the citizen that a new TrustID request is awaiting review
and directs them to TrustID. Its sender is **TrustID**. The notification and
preview may identify the requesting organization and general request type, but
must not contain a NIN, licence number, raw identifier, protected attribute
value, PIN/OTP detail, or other sensitive source data.

The centralized TrustID Phone is the development/demo representation of a
citizen's personal phone. It is not a public message lookup service. In
production, TrustID sends through the citizen's actual mobile provider to the
registered number; production must never expose an arbitrary-number inbox that
any visitor can open by typing a number.

For the demo phone, inbox ownership is persistent per registered phone number,
not per temporary browser/phone session:

- connecting or switching to a number displays only that number's messages;
- switching numbers does not delete, transfer, or mark messages in either
  inbox, and returning to a number restores its existing inbox;
- newest messages appear first and a sensible page or record limit applies;
- new messages start unread, opening a message atomically sets `opened_at`, and
  the unread count updates from rows whose `opened_at` is null; and
- each inbox row shows sender, privacy-safe preview, delivery time, and read or
  unread status. Message details remain scoped to the current registered phone
  context.

Notification delivery state is operational metadata, not consent state.
Record pending/sent/failed delivery safely, including delivery/attempt time and
a bounded provider-neutral failure code where useful. Never store provider
payloads or error text that may echo message content or phone numbers. A send
failure leaves the verification and consent request pending and available for
later retry or Phase 8 review; it does not roll back or cancel them.

The one-time submission reference and a unique consent-notification association
must make retries idempotent: duplicate form submissions or delivery retries
must not create a second consent request or a second logical SMS message.
Email is an optional later notification channel only if time permits; Phase 5
must not depend on email.

#### Necessary SMS migration only

Reuse `sms_deliveries`, `phone_sessions`, `citizens.registered_phone`, and
`opened_at`. Do not introduce a parallel inbox table merely for Phase 5.
The Phase 5 migration needs only to:

- add nullable `citizen_id` to `sms_deliveries`, index it for newest-first inbox
  and unread-count queries, and backfill it through existing
  `otp_challenges.citizen_id`; this becomes the persistent inbox association,
  while `phone_session_id` remains transport/session history rather than inbox
  ownership;
- add a nullable, unique `consent_request_id` foreign key so one consent request
  maps to at most one logical SMS delivery;
- allow OTP-only fields (`challenge_id`, `access_token_hash`, and `code_nonce`)
  to be null for non-OTP consent notifications while retaining their existing
  uniqueness and activation behavior when present; and
- add bounded delivery status/timestamp/failure-code fields if the existing
  delivery adapter cannot otherwise record pending, sent, and failed outcomes.

`message_type='CONSENT'`, `created_at`, `expires_at`, and `opened_at` already
exist and must be reused. Sender, standard preview, and standard body can be
derived from the message type and safe related metadata; new free-form content
columns are unnecessary unless implementation proves that fixed templates
cannot meet the product requirement.

### History, probing preparation, and isolation

- Show pending and recent requests with verification reference, type,
  plain-language condition, status/result, creation time, expiry time, and a
  details action. Paginate or enforce a sensible limit.
- Scope every pending, result, detail, and history query by the authenticated
  organization ID. Guessing another organization's URL or reference must reveal
  nothing.
- Begin privacy-safe `request_history` recording for age checks in Phase 5 so
  Phase 9 has its required input. Store organization, organization-scoped
  subject reference, claim family, operator, thresholds, Boolean result, and
  timestamp—never NIN, date of birth, or exact age.

### Verification coverage

- Add end-to-end tests for forged claim submissions, status/category changes
  between render and submission, duplicate submission, unsafe purpose text,
  cross-organization reference guessing, correct TTLs, consent expiry, safe
  source errors, SMS send failure, persistent per-number inbox isolation,
  newest-first ordering, unread/open behavior, unread counts, number switching,
  and absence of raw source values in responses, SMS content, delivery errors,
  and all persistent/audit records.
- Verify that duplicate submission/retry creates one pending verification, one
  consent request, and one logical SMS notification, and that notification
  failure does not cancel the pending request.
- Confirm custom-category permission changes appear immediately and flexible
  age comparisons and ranges remain supported.
- Add a Phase 5 acceptance script, retain all Phase 2–4 regression checks, and
  include the new script in the documented verification sequence.

## Explicit non-goals

Phase 5 does not weaken claim privacy modes, allow organizations to select
citizen confirmation methods, resolve citizen consent, or release protected
direct attributes. It creates the pending consent records, while Phase 8 adds
the citizen request list/detail experience, approval or rejection,
authentication, multi-channel decision handling, and controlled-disclosure
lifecycle. Phase 5 creates the request and privacy-safe notification only.
Request-limit and inference-risk detectors remain Phase 9 controls; Phase 5
records their privacy-safe request-history input and preserves the policy hooks.

## Completion evidence expected

Phase 5 is ready to close when unit tests and its database-backed acceptance
script demonstrate the guided portal flow, server-side policy enforcement
before source access, successful instant predicate checks, correct freshness,
duplicate protection, pending consent creation and expiry, organization
isolation, one privacy-safe consent SMS, persistent per-number inbox behavior,
safe non-fatal delivery failure, privacy-safe request history, and no raw
identifiers or source attributes in results, messages, delivery metadata,
history, receipts, or audit details. All Phase 2–4 regression checks must
continue to pass.
