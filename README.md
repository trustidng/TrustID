# TrustID — Phase 8: Citizen Approval and Controlled Disclosure

TrustID now includes the Phase 1 synthetic sources, Phase 2 authentication,
the internal Phase 3 predicate-verification engine, the Phase 4 centralized
policy engine, organization verifier portal, signed receipts, verification
history, protected photographs, and citizen-controlled disclosure.

## Important data-safety warning

`db/schema.sql` and `db/seed_data.py` are destructive Phase 1 demo-reset tools.
Do not run either against data you want to keep. Phase 2 uses the separate,
non-destructive migration runner.

## First-time setup

1. Create a database: `CREATE DATABASE trustid;`
2. Load the schema: `mysql -u <user> -p trustid < db/schema.sql`
3. Copy `.env.example` to `.env` and fill in your DB credentials
4. Create and activate a virtual environment.
5. `pip install -r requirements.txt`
6. Add strong, different `SESSION_SECRET` and `PSEUDONYM_HMAC_SECRET` values to `.env`.
7. `python db/migrate.py`
8. `python db/seed_data.py` (first-time/demo reset only)
9. `uvicorn app.main:app --reload`
10. Open `http://127.0.0.1:8000`

If this project was copied from another location, recreate the virtual
environment rather than copying `venv`; Windows virtual environments retain
absolute paths to their original Python installation.

## What you get after seeding

- 1 administrator with a one-time setup password that must be replaced at first sign-in
- 8 organisations covering every status (PENDING/APPROVED/REJECTED/SUSPENDED)
  and every category including GOVERNMENT
- 302 citizens, including two explicit boundary-case citizens
  ("Exactly Eighteen Test", "Exactly Thirty Test") for the age-predicate
  acceptance tests in Phase 0 §9 (#3/#4)
- ~161 licences with a realistic VALID/EXPIRED/SUSPENDED spread

## Phase 2 routes

- `/admin/login` — administrator sign-in and organization review
- `/admin/administrators` — primary-administrator account management
- `/admin/organisations/{id}/verifications` — audited, privacy-safe organization verification history
- `/organisation/register` — submit an organisation application
- `/organisation/login` — every organisation status may sign in
- `/organisation` — status-aware verifier dashboard with recent and pending requests
- `/organisation/verifications/new` — permission-filtered guided verification flow
- `/organisation/verifications/{reference}` — organization-isolated privacy-safe result or request status
- `/citizen/activate` — SMS activation-code delivery and TrustID PIN creation
- `/citizen/login` — citizen phone/PIN sign-in
- `/phone` — centralized TrustID Phone home for Messages and Dialler
- `/phone/messages` — SMS inbox for activation and future TrustID notifications
- `/phone/messages/{message-id}` — individual message view with received time and active/expired state
- `/phone/dialer` — dial `*7305#` for USSD activation and PIN access
- `/phone/inbox/{access-token}` — internal secure message-delivery handoff (not displayed in the user interface)
- `/ussd` — compatibility redirect to the centralized phone dialler
- `/health` — application/database health check

The organization verifier portal uses the Phase 4 policy engine before every
trusted-source lookup. Administrative governance supports multiple
role-separated accounts and privacy-safe organization verification oversight;
see `docs/Admin_Governance.md`.

## Security behavior

- Passwords and PINs are bcrypt-hashed.
- Sessions are random, server-side, expiring, revocable, and stored only as hashes.
- Authenticated form mutations require a CSRF token.
- OTPs expire, are single-use, and are stored only as keyed hashes.
- Repeated failures temporarily lock an account.
- Login errors are deliberately generic.
- Organisation status changes follow the frozen transition rules.
- USSD conversations are server-side, short-lived and stored under hashed opaque tokens.

## Citizen activation states

- `account_activated=FALSE` and `pin_hash=NULL` means the citizen has not created a TrustID account.
- An eligible inactive citizen receives an activation code in the TrustID Phone SMS inbox.
- `account_activated=TRUE` with a populated `pin_hash` means the account is already active.
- An already-active citizen is directed to sign in; TrustID does not create another activation message.
- Activation messages begin with “Welcome to TrustID” and codes remain single-use and time-limited.

The demo SMS delivery adapter is replaceable with a production SMS provider;
the OTP generation, hashing, expiry and activation workflow remain unchanged.

The centralized TrustID Phone represents a citizen's personal phone for local
development and demos. Each registered phone number has a separate persistent
inbox: newest messages appear first, new messages are unread, opening one marks
it read, and switching numbers changes the visible inbox without clearing
either number's messages. Production sends SMS through the citizen's actual
mobile provider and must never expose an arbitrary-number public inbox.

USSD follows a one-response-per-screen conversation. Inactive citizens receive
an activation menu, while active citizens proceed directly to the PIN prompt.
PIN creation and PIN confirmation are separate steps, `0` returns to the menu,
and Cancel ends the session. Interim PIN values are never stored; only a bcrypt
hash is retained for the brief confirmation step. Each response renews the
three-minute conversation timeout.

## Tests

Run `pytest -q`, then `python scripts/verify_admin_governance.py` and
`python scripts/verify_phase2.py` through `python scripts/verify_phase8.py`
against the configured local database. The verification scripts create and
clean up temporary acceptance-test records; they do not reset the database.

## Phase 3 verification engine

- Separate in-process identity and licensing authority adapters
- Flexible age comparisons: older than, at least, younger than, not older than, and inclusive ranges
- Identity status, licence status, and licence class predicates
- Correct birthday, boundary, expiry-date, and leap-year handling
- Organisation-scoped HMAC subject references
- Verifier-safe results that exclude internal IDs and private source values
- Plain-language labels for the future non-technical verifier portal
- Safe trusted-source, validation, and unexpected-error responses
- No public verification endpoint before central policy enforcement exists

The identity authority now models `state_of_origin` and
`residential_address` separately. Existing synthetic state values are
preserved as state of origin; fictional addresses are backfilled and generated
for all future synthetic citizens. See
`docs/Architecture_Amendment_001_Identity_Attributes.md` for the Phase 4
permission and consent rules that supersede the earlier state-of-residence
simplification.

## Phase 4 policy engine

- Database-driven custom organization categories
- Administrator-selected claim permissions
- Immutable claim privacy modes outside category administration
- Approval status checked before claim permissions
- Standard instant, consent, strong-consent, and denial decisions
- Professional organization-facing messages
- Available verification options filtered by assigned permissions
- Privacy-safe policy audit records
- Hooks for the Phase 9 request-limit and inference-risk controls

See `docs/Phase4_Policy_Engine.md` for the decision order and security boundary.
It also defines the category, permission, organization, and policy-decision
lifecycles that Phase 5 must preserve.

## Phase 5 verifier portal

The implemented Phase 5 behavior and security contract are documented in
`docs/Phase5_Readiness.md`. Every submitted verification receives a fresh
policy decision before any trusted-source lookup. Instant checks return only a
limited result with the correct freshness period. Consent-required submissions
create pending verification and consent records plus one privacy-safe SMS
notification. Phase 8 remains responsible for citizen review, authenticated
approval/rejection, and controlled disclosure.

The implemented scope follows `Phase0_Architecture_Freeze.md` and
`TrustID_Build_Plan.md`.

## Phase 6 signing and tamper detection

The implemented Phase 6 contract is in
`docs/Phase6_Readiness.md`. Phase 6 adds Ed25519 signatures to completed
privacy-safe verification results, a QR-based authenticity link, distinct
current/expired/altered result states, external private-key handling, public-key
rotation, and a controlled tamper demonstration. Pending consent requests are
not signed; Phase 8 signs direct-disclosure results only after a valid citizen
decision produces a completed result.

New completed instant results receive a signed receipt, QR code, and shareable
authenticity link. Existing Phase 5 results remain clearly labelled as created
before signing was enabled. Use `scripts/setup_signing_key.py` to rotate a
local development key and `scripts/verify_phase6.py` for database acceptance.
Application startup validates that the configured private key matches the one
active public key. Public authenticity checks use a bounded global database
counter that stores no visitor identifier, and QR acceptance tests decode the
generated image back to its exact verification URL.

For a visual, disposable tamper demonstration, run
`python scripts/tamper_demo.py create`, open the printed link, then run
`python scripts/tamper_demo.py alter` and refresh the same page. Use `restore`
to return it to its authentic state and `cleanup` when finished. The script
refuses to modify records that do not carry its exact development-only marker.

## Phase 7: privacy-safe verification history and receipts

The completed Phase 7 contract is in `docs/Phase7_Readiness.md`. Organizations
now use one **Verification history** centre with separate all-request and
receipt views, privacy-safe reference search, allowlisted filters, pagination,
and responsive tables. Every signed result has an organization-isolated receipt
page with live authenticity and freshness status, QR verification, copy/share
actions, a clearly separated verification purpose, related-verification navigation,
and print/save styling. Run `scripts/verify_phase7.py` for the database-backed
500-record load, isolation, tamper, privacy, and route acceptance check.

## Independent authorities and protected identity photographs

`docs/Architecture_Amendment_002_Independent_Authorities_and_Photographs.md`
documents the implemented post-Phase-7 refinement. The synthetic national
identity and driver licensing authorities are now standalone sources. Completed
organization results temporarily display a protected fictional identity
photograph for visual comparison, while history, receipts, QR codes, and public
authenticity pages remain photograph-free. Run
`scripts/verify_authority_photographs.py` for the database-backed independence,
access-control, audit, rate-limit, and privacy checks.

## Phase 8: citizen approval and controlled disclosure

The implemented Phase 8 contract is in `docs/Phase8_Readiness.md`. Citizens use
a simple **Needs your attention** and **Previous requests** account experience.
Web approval requires the TrustID PIN and one SMS confirmation code; web
decline requires the PIN. The TrustID Phone USSD journey authenticates once and
then provides short request, detail, approval, decline, and recent-decision
screens without an additional code.

Approved legal-name, state-of-origin, and residential-address values are
encrypted, organization-isolated, and current for 30 days. They appear only on
the requesting organization's private completed result. History, SMS, audit
details, receipts, QR codes, administrator pages, and public authenticity pages
never receive the protected value. Consent SMS is limited to the initial
request and the web approval code. Run `scripts/verify_phase8.py` for the
database-backed decision, encryption, receipt, isolation, privacy, USSD, and
SMS-cost acceptance check.
