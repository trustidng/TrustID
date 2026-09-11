# TrustID Railway staging deployment

This deployment is a review environment. It uses its own MySQL database,
evidence volume, secrets, and public address. It does not connect to or alter
the local development database.

## Services

Create one Railway project containing:

1. A service deployed from the `trustidng/TrustID` GitHub repository.
2. A Railway MySQL service.
3. A volume attached to the application service at
   `/app/var/organisation-evidence`.

Keep the MySQL service private. The application connects over Railway's private
network through reference variables.

## Application variables

Set these on the application service. Choose the MySQL service from Railway's
variable-reference suggestions instead of copying its credentials manually.

```text
DB_HOST=${{MySQL.MYSQLHOST}}
DB_PORT=${{MySQL.MYSQLPORT}}
DB_USER=${{MySQL.MYSQLUSER}}
DB_PASSWORD=${{MySQL.MYSQLPASSWORD}}
DB_NAME=${{MySQL.MYSQLDATABASE}}
PUBLIC_BASE_URL=https://${{RAILWAY_PUBLIC_DOMAIN}}
COOKIE_SECURE=true
EVIDENCE_STORAGE_PATH=/app/var/organisation-evidence
SESSION_TTL_HOURS=12
OTP_TTL_MINUTES=10
AUTH_MAX_ATTEMPTS=5
AUTH_LOCK_MINUTES=15
USSD_SESSION_TTL_MINUTES=3
```

Add independent strong values for `SESSION_SECRET` and
`PSEUDONYM_HMAC_SECRET`. Add the existing staging receipt-signing key as
`TRUSTID_SIGNING_PRIVATE_KEY_B64` and its matching identifier as
`TRUSTID_SIGNING_KEY_ID`. Seal all four secret values in Railway after the
first successful deployment.

Do not upload `.env` to Railway or commit it to Git.

## Database initialization

The application start command runs `python db/migrate.py` before starting the
web server. The migration runner is forward-only and safe to run on every
deployment.

For a copy of the existing demonstration environment, import a MySQL dump of
the local `trustid` database before starting the application. Do not run
`db/schema.sql` or `db/seed_data.py` after importing the dump because both are
demo reset tools.

If starting with an empty Railway database instead, load `db/schema.sql` once,
run `db/seed_data.py` once, create a receipt-signing key, and then deploy.

## Public service settings

- Generate a Railway domain for the application service.
- Configure `/health` as the health-check path (also declared in
  `railway.toml`).
- The application listens on Railway's injected `PORT` value.
- Do not enable public networking for MySQL.
- Enable automatic deployments from `main` only after the first successful
  staging review.

## Evidence files

Database rows do not contain the uploaded evidence files. To reproduce the
current demo exactly, copy the contents of local `var/organisation-evidence`
into the attached Railway volume. Otherwise, evidence already referenced by
the imported database will show as unavailable.

Use only synthetic demonstration records and documents in this environment.
