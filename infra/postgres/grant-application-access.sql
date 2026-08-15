\set ON_ERROR_STOP on

GRANT USAGE ON SCHEMA erp TO erp_app, erp_backup;

GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA erp TO erp_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA erp TO erp_app;

-- Append-only event ledgers: the application may read and append, never rewrite
-- or erase history.
REVOKE UPDATE, DELETE, TRUNCATE ON TABLE
    erp.audit_event,
    erp.access_event,
    erp.auth_event,
    erp.system_run_event
FROM erp_app;

-- These compatibility tables were superseded by the current W2 ledger.  Keep
-- them read-only even though the broad baseline grant above covers all tables.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
    erp.recipient_plan_notification,
    erp.recipient_service_plan_notice
FROM erp_app;

REVOKE USAGE, UPDATE ON SEQUENCE
    erp.recipient_plan_notification_id_seq,
    erp.recipient_service_plan_notice_id_seq
FROM erp_app;

GRANT SELECT ON ALL TABLES IN SCHEMA erp TO erp_backup;

ALTER DEFAULT PRIVILEGES FOR ROLE erp_owner IN SCHEMA erp
    GRANT SELECT, INSERT, UPDATE ON TABLES TO erp_app;
ALTER DEFAULT PRIVILEGES FOR ROLE erp_owner IN SCHEMA erp
    GRANT USAGE, SELECT ON SEQUENCES TO erp_app;
ALTER DEFAULT PRIVILEGES FOR ROLE erp_owner IN SCHEMA erp
    GRANT SELECT ON TABLES TO erp_backup;
