# TrustID Phase 10 — Phone, Messaging and Service Resilience

## Goal

Ensure TrustID fails safely and recovers cleanly when an identity, driving-licence or SMS service is temporarily unavailable, while completing the low-technology Phone, SMS and USSD experience.

## Service behavior

The Admin **Security** centre displays the operational status of the national identity, driving-licence, SMS and USSD services. Authorized administrators may mark a service unavailable and restore it. Every change records the administrator account, previous and new status, reason and time. Attempted use of an unavailable service is also audited.

An unavailable trusted source never produces a verification result, photograph or signed receipt. The existing submission remains safe to retry after recovery. An unavailable SMS service never displays a failed delivery in the citizen's inbox. Pending approval requests remain accessible through the citizen portal and USSD even if their notification could not be delivered.

## Professional messages

- Identity: **The identity verification service is temporarily unavailable. Please try again later.**
- Driving licence: **The driving licence verification service is temporarily unavailable. Please try again later.**
- SMS: **The confirmation code could not be sent at this time. Please try again later.**
- USSD expiry: **Your session has ended for your security. Please dial *7305# to start again.**
- USSD maintenance: **TrustID USSD is currently unavailable due to maintenance. Please try again later.**

Messages do not expose record existence, internal exceptions, database details or service configuration.

## Completion gates

- each trusted source fails closed and recovers successfully;
- failed source requests create no verification or receipt;
- approval disclosure is prevented while its source is unavailable;
- SMS notification and confirmation-code failures are recorded accurately;
- failed SMS deliveries never appear as received messages;
- activation handles SMS unavailability safely;
- expired and interrupted USSD sessions recover clearly;
- administrative service controls require authentication and CSRF protection;
- status changes and unavailable-service events are audited;
- service states remain independent; and
- Phase 2–10 regression acceptance passes.
