-- The citizen functions' own database role: it reads and writes the six
-- citizen tables and nothing else -- no cases, letters, labels or watches,
-- and no DELETE anywhere. Run once, as the database owner, after the main
-- app has migrated (the tables must exist). Its password is set apart from
-- this file (docs/citizen-deploy.md).
CREATE ROLE exchequer_citizen LOGIN NOINHERIT CONNECTION LIMIT 20;
GRANT USAGE ON SCHEMA public TO exchequer_citizen;
GRANT SELECT, INSERT ON complaints, complaint_payments, complaint_messages, tracking_codes, citizen_sessions, citizen_attempts TO exchequer_citizen;
GRANT UPDATE (wallet_match, updated_at) ON complaints TO exchequer_citizen;
GRANT UPDATE (expires_at) ON citizen_sessions TO exchequer_citizen;
GRANT UPDATE (count, first_at, last_at) ON citizen_attempts TO exchequer_citizen;
