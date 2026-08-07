-- Runs once, on first initialisation of the Postgres data volume.
-- Creates the separate test database that TEST_DATABASE_URL points at
-- (pytest refuses to run if it shares a database with DATABASE_URL).
CREATE DATABASE backlogg_test;
