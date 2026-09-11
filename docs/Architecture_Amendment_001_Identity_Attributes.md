# Architecture Amendment 001 — Identity Direct-Disclosure Attributes

This amendment supersedes the earlier Phase 0 treatment of `state_of_residence`
as the source for `RESIDENTIAL_ADDRESS`.

## Synthetic identity authority

The identity source contains two separate attributes:

- `state_of_origin`: the citizen's synthetic registered state of origin.
- `residential_address`: the citizen's full fictional demo address.

State of origin must never be presented as proof of a current residential
address. State of origin and residence location are generated independently,
so a citizen may originate from Yobe and reside in Lagos, Abuja, or any other
state. Some may naturally match. Every residential address in the demo dataset
is fictional.

## Claim catalogue additions

| Claim | Source field | Disclosure rule | TTL class |
|---|---|---|---|
| `FULL_LEGAL_NAME` | `full_name` | Citizen consent | `CONSENT` |
| `STATE_OF_ORIGIN` | `state_of_origin` | Citizen consent | `CONSENT` |
| `RESIDENTIAL_ADDRESS` | `residential_address` | Strong citizen consent | `CONSENT` |

There is no exemption path for these disclosure requirements. Consent cannot
grant a claim that the organisation's category is not permitted to request.

## Category permissions for Phase 4

| Category | Permitted claims |
|---|---|
| `RETAIL` | `AGE_COMPARE`, `IDENTITY_STATUS` |
| `PROGRAMME_OPERATOR` | `AGE_COMPARE`, `IDENTITY_STATUS`, `FULL_LEGAL_NAME` (consent), `STATE_OF_ORIGIN` (consent) |
| `GOVERNMENT` | `AGE_COMPARE`, `IDENTITY_STATUS`, `FULL_LEGAL_NAME` (consent), `STATE_OF_ORIGIN` (consent), `RESIDENTIAL_ADDRESS` (strong consent) |
| `FINANCIAL` | `AGE_COMPARE`, `IDENTITY_STATUS`, `FULL_LEGAL_NAME` (consent), `STATE_OF_ORIGIN` (consent), `RESIDENTIAL_ADDRESS` (strong consent) |
| `TRANSPORT_LOGISTICS` | `LICENCE_STATUS`, `LICENCE_CLASS`, `IDENTITY_STATUS` |

Category permission and disclosure mode are separate controls. Future category
management may remove or grant a category's eligibility for a claim, but it
must never weaken a claim's mandatory consent level.

## Consent confirmation by channel

| Channel and decision | Required confirmation |
|---|---|
| Citizen web approval | TrustID PIN followed by a one-time SMS code sent to the registered number |
| Citizen web rejection | TrustID PIN |
| USSD approval | Trusted registered originating number and TrustID PIN; no additional OTP |
| USSD rejection | Trusted registered originating number and TrustID PIN |

In production, the originating number must come from the trusted
telecommunications gateway and must never be accepted from a user-supplied
form field. The organisation is never shown which confirmation mechanism or
channel the citizen used. The first valid decision across channels closes the
request atomically.

## Professional user-facing messages

| Situation | Message |
|---|---|
| Verification permitted | You can proceed with this verification. |
| Citizen approval required | The citizen's approval is required to continue. |
| Organisation not approved | Your organization must be approved before it can request verifications. |
| Claim not permitted | Your organization is not authorized to request this verification. |
| Approval pending | Awaiting the citizen's approval. |
| Request rejected | The citizen declined this request. |
| Approval expired | The approval request has expired. Please create a new verification request. |
| Requirement satisfied | The requirement was met. |
| Requirement not satisfied | The requirement was not met. |
| Source unavailable | This verification service is temporarily unavailable. Please try again later. |
| Invalid request | Please check the verification details and try again. |

Internal policy enums, consent strength, PIN and OTP mechanics, HMAC details,
and inference controls must not be exposed in organisation-facing messages.
