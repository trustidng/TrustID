# TrustID Phase 9 — Abuse and Inference Controls

## Goal

Stop one organization from reconstructing a citizen's protected age through repeated verification requests while preserving normal activity involving other organizations or citizens.

## Frozen MVP rule

TrustID permits three age-verification requests for the same organization-specific citizen reference within a rolling 30-minute window. A fourth request is blocked before an age result is generated. Counters are isolated by organization, citizen reference and claim family. Duplicate submission tokens return their original decision and do not increment the count.

The organization sees: **This verification cannot continue because too many similar requests were made recently. Please try again later.** The precise threshold and internal detection state are not disclosed.

## Privacy boundary

Monitoring records contain the organization, organization-specific citizen reference, age claim family, requested condition, decision and timestamp. They never contain a raw NIN, name, date of birth, exact age, photograph, address or verification answer.

## Administrative oversight

The Admin **Security** centre provides privacy-safe metrics, filters, incident records, explanations and links to organization management. Security views are audited. Administrators can use the existing organization lifecycle controls when repeated incidents warrant suspension.

## Required completion gates

- fourth same-organization/same-citizen age request blocked in a rolling 30-minute window;
- blocked request produces no verification result or receipt;
- duplicate submissions count once;
- concurrent submissions cannot bypass the limit;
- different organizations and different citizens remain isolated;
- exact 30-minute boundary expires correctly;
- non-age requests are unaffected;
- security records contain no verification answer or direct citizen identifier;
- Admin Security metrics, filters, incident details and authorization work;
- large-history queries use scoped indexes; and
- Phase 2–9 regression acceptance passes.

The interval-narrowing state machine remains an optional enhancement after the explainable MVP is stable.
