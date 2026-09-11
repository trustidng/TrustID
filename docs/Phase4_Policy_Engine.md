# TrustID Phase 4 — Policy Engine

## Purpose

Phase 4 is the single authorization boundary between an organization and the
Phase 3 trusted-source verification engine. A future verification endpoint must
obtain a permitted policy decision before looking up a citizen or licence.

## Decision order

1. Confirm that the organization exists and is `APPROVED`.
2. Confirm that its assigned category is active.
3. Confirm that the category is permitted to request the claim.
4. Apply request-limit and inference-risk controls when those detectors report a block.
5. Apply the claim's immutable privacy mode: instant, consent, or strong consent.

Consent never overrides category permission.

## Dynamic categories

Administrators may create, rename, enable, disable, and select permissions for
organization categories. Category codes are immutable identifiers. Categories
are disabled instead of deleted, preserving existing assignments and audit
history. Permission changes take effect immediately for every assigned
organization.

The administrator controls claim eligibility only. Claim privacy modes are
stored separately and cannot be edited on the category-management screen.

## Category and permission lifecycle

1. **Create.** An administrator supplies a unique name, immutable code,
   description, and initial claim selection. The category and its permissions
   are stored together and are immediately available for new organization
   applications.
2. **Assign.** An organization selects an active category when applying. An
   administrator confirms an active category when approving the application.
   The organization stores the category identifier, so later name changes do
   not break the assignment.
3. **Update.** An administrator may change the display name, description,
   active state, and complete permission selection. The code is never edited.
   Saving replaces the permission set; additions and removals affect every
   assigned organization on its next policy decision.
4. **Disable.** A disabled category is retained, but disappears from new
   application and approval choices. Assigned organizations keep their
   historical relationship while receiving no available claims and no new
   authorization. Disabling does not alter the organizations' approval status.
5. **Re-enable.** Re-enabling restores the category as an assignment choice and
   makes its currently selected permissions effective again. It does not
   restore permissions that were removed before or while it was disabled.

Categories are not deleted through the application. This preserves foreign-key
relationships and audit history. Category creation, metadata/state changes,
and permission replacement produce administrator audit events. Audit details
use category codes and claim codes, not citizen data.

## Organization lifecycle interaction

Policy authorization is independent from authentication. Every decision
re-checks the organization's current approval status, category state, and
current permission set.

The allowed administrator-controlled status transitions are:

- `PENDING → APPROVED`
- `PENDING → REJECTED`
- `APPROVED → SUSPENDED`
- `SUSPENDED → APPROVED` (reinstatement)

`REJECTED` is terminal in the current lifecycle. All other status changes are
rejected server-side.

Consequently:

- `PENDING`, `REJECTED`, and `SUSPENDED` organizations receive no claims and
  cannot obtain an allowed policy decision;
- suspending an organization also revokes its active organization sessions;
- reinstatement restores the existing category assignment, but access still
  depends on that category being active and retaining the requested claim; and
- changing category permissions does not require organizations to sign out or
  sign in again before the new policy result applies.

The organization status check intentionally precedes the claim-permission
check, so an unapproved organization cannot use denial differences to discover
its category's permission set.

## Policy-decision lifecycle

For each attempted verification, the caller asks the policy engine for one
claim decision. The engine validates the claim code, evaluates the controls in
the documented order, records one privacy-safe `POLICY_DECISION` event, and
returns a professional message with one of these outcomes:

| Outcome | Caller action |
|---|---|
| `ALLOW_INSTANT` | Phase 5 may invoke the Phase 3 engine immediately. |
| `REQUIRE_CONSENT` | Phase 5 creates a pending standard approval request without a source lookup or disclosure. |
| `REQUIRE_STRONG_CONSENT` | Phase 5 creates a pending strong approval request without a source lookup or disclosure. |
| Any `DENY_*` result | Stop without performing a trusted-source lookup. |

Phase 4 returns policy decisions only. It does not create verification or
consent records, resolve citizen approvals, or call a trusted source. Phase 5
creates the pending records; Phase 8 resolves citizen decisions and controls
the eventual disclosure. A future endpoint must not treat portal filtering, a
previous decision, or an existing login session as authorization for a new
lookup.

## Portal filtering and enforcement

Approved organizations receive only the active claims permitted for their
category. Other claims are omitted from the interface. This filtering is for
clarity, not security: every submitted request must still be authorized by the
policy engine, including manually constructed requests.

## User-facing language

Organizations see professional messages rather than internal enums. Both
consent levels use “The citizen's approval is required to continue.” PIN, OTP,
HMAC, inference detection, and consent-strength details remain internal.

## Audit boundary

Every policy decision records only `claim_code`, `decision`, and `reason_code`.
Raw NINs, licence numbers, names, dates of birth, origins, addresses, and user
conditions are never written to the policy audit detail.

## Phase 5 integration contract

The verifier portal must obtain its menu from `available_claims()` and call
`decide()` again after validating each submitted request. Only
`ALLOW_INSTANT` may cross directly into the Phase 3 engine. The portal must
preserve the policy message returned to the organization and keep raw citizen
identifiers and conditions out of policy audit details.

Consent-required outcomes are valid Phase 4 results. Phase 5 must create the
pending verification and consent records, enqueue one idempotent privacy-safe
SMS notification to the citizen's registered phone, and present the
approval-required state. SMS failure does not cancel the pending request.
Phase 5 must not simulate approval, downgrade the request to an instant check,
query the trusted source, or release the protected value. Phase 8 adds citizen
review, authenticated approval/rejection, and controlled disclosure.
