-- ============================================================================
-- Ingestion DDL down-script: removes every project object the up-script made
-- ============================================================================
-- TEST DATABASE ONLY. This script exists so tests can prove the up-script
-- creates the full object set from an empty database and leaves nothing
-- behind when reversed. It must never run against wifi_beacon_survey: the
-- production database is a projection whose recovery is the operator's
-- DROP DATABASE, never an executor action, and no executor drops anything.

DROP SCHEMA IF EXISTS derived CASCADE;
DROP SCHEMA IF EXISTS ingest CASCADE;
DROP SCHEMA IF EXISTS archive CASCADE;
DROP SCHEMA IF EXISTS survey CASCADE;
