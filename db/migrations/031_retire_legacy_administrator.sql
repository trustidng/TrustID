-- Retain the historic administrator record for accountability while removing access.

UPDATE admin_users
SET active=FALSE,
    failed_login_attempts=0,
    locked_until=NULL
WHERE username='vaisahzirra7';

DELETE FROM auth_sessions
WHERE actor_type='ADMIN'
  AND actor_id IN (SELECT id FROM admin_users WHERE username='vaisahzirra7');
