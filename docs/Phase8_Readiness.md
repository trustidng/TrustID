# TrustID Phase 8 — Citizen Approval and Controlled Disclosure

## Status

This is the frozen implementation contract for Phase 8. It builds on the
pending approval records, citizen authentication, TrustID Phone, policy engine,
signed receipts, organization history, and protected photographs completed in
Phases 2–7.

## Goal

Allow a citizen to understand and decide a request for a legal name, state of
origin, or residential address, and release only the approved field to the
requesting organization.

## Lifecycle

Requests move once from `PENDING` to `APPROVED`, `REJECTED`, or `EXPIRED`.
The first valid web or USSD decision wins atomically. Decisions cannot be
reversed. Requests remain open for 24 hours. Approved information is current
for 30 days.

## Citizen experience

The web account has two simple sections: **Needs your attention** and
**Previous requests**. A request explains the organization, information,
purpose, and expiry before presenting **Approve request** and **Decline
request**.

Web approval requires PIN confirmation followed by a ten-minute SMS code. Web
decline requires the PIN only. USSD authenticates once at the beginning of its
short session and then provides a compact menu for pending requests and recent
decisions; it does not send an additional code or display the protected value.

## SMS cost control

Consent SMS is limited to a new-request notification and a web-approval code.
There are no routine decision, expiry, receipt, login, USSD, or reminder
messages. Existing activation and PIN-reset messages remain. Critical security
alerts must be rate-limited.

## Authorization and disclosure

Immediately before approval, TrustID rechecks request ownership and expiry,
organization approval, active category and current claim permission, citizen
and source-record status, and the absence of an earlier decision. Only then is
the single requested attribute loaded.

The value is encrypted with AES-256-GCM using a domain-separated key derived
from protected application key material. Its organization, verification,
claim, and version are authenticated as associated data. The value never
appears in history tables, SMS, audit details, receipts, QR codes, public
authenticity pages, URLs, photographs, or browser storage. It is available only
to the requesting organization while current.

Approved disclosures produce exactly one existing-format signed receipt. The
receipt proves the disclosure event but does not contain the personal value.
Organization wording is **Information provided**; rejected or expired requests
receive no receipt.

## Required completion gates

- web approve with PIN and SMS code;
- web decline with PIN;
- USSD approve and decline after one session PIN;
- atomic first-decision-wins behavior across channels;
- OTP attempt, resend, and expiry protection;
- policy and source recheck before disclosure;
- encrypted, organization-isolated, expiring disclosure;
- privacy-safe organization and administrator views;
- no receipt for rejected or expired requests;
- no protected value in non-private surfaces;
- desktop, mobile, and USSD experience checks; and
- complete Phase 2–8 regression acceptance.

## Implementation verification

Phase 8 is implemented. The citizen account now provides card-based **Needs
your attention** and **Previous requests** sections, organization/purpose/
information request details, PIN-confirmed web decline, and PIN plus SMS-code
web approval. The TrustID Phone USSD service authenticates once per short
session and provides concise pending-request, detail, confirmation, and recent-
decision screens.

The forward-only `020_phase8_consent_disclosure.sql` migration adds decision
evidence, consent approval challenges, protected disclosure storage, USSD
states, and privacy-safe audit events. Approved values are encrypted with
authenticated encryption, scoped to the requesting organization, current for
30 days, and absent from history, SMS, administrator content, receipts, QR
codes, and public authenticity pages. Only the new-request message and web
approval code are sent for the normal consent journey.

`scripts/verify_phase8.py` exercises the real web and USSD routes, private
organization result and cross-organization denial, web approval and decline,
USSD approval and decline, close-only completion screens, encrypted storage,
30-day validity, receipt uniqueness, protected
value privacy, and SMS cost controls. All earlier phase and governance gates
remain mandatory regressions.
