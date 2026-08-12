\set ON_ERROR_STOP on

\prompt -s 'erp_owner password: ' erp_owner_password
\prompt -s 'erp_app password: ' erp_app_password
\prompt -s 'erp_backup password: ' erp_backup_password

SELECT format('CREATE ROLE erp_owner LOGIN PASSWORD %L', :'erp_owner_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_owner')
\gexec

SELECT format('CREATE ROLE erp_app LOGIN PASSWORD %L', :'erp_app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_app')
\gexec

SELECT format('CREATE ROLE erp_backup LOGIN PASSWORD %L', :'erp_backup_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_backup')
\gexec

ALTER ROLE erp_owner SET timezone = 'UTC';
ALTER ROLE erp_app SET timezone = 'UTC';
ALTER ROLE erp_app SET search_path = erp, pg_catalog;
ALTER ROLE erp_app SET statement_timeout = '30s';
ALTER ROLE erp_app SET lock_timeout = '5s';
ALTER ROLE erp_app SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE erp_backup SET timezone = 'UTC';

\unset erp_owner_password
\unset erp_app_password
\unset erp_backup_password
