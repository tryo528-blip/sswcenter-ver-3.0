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

DO $$
BEGIN
    IF to_regclass('erp.w3_private_content') IS NOT NULL THEN
        REVOKE UPDATE, DELETE, TRUNCATE ON TABLE
            erp.w3_private_content,
            erp.w3_source_receipt,
            erp.w3_source_snapshot,
            erp.w3_import_run,
            erp.w3_import_attempt,
            erp.w3_source_row
        FROM erp_app;
        GRANT UPDATE (status) ON TABLE erp.w3_source_snapshot TO erp_app;
        IF EXISTS (
            SELECT 1
              FROM information_schema.columns
             WHERE table_schema = 'erp'
               AND table_name = 'w3_import_run'
               AND column_name = 'row_version'
        ) THEN
            GRANT UPDATE (status, row_version) ON TABLE erp.w3_import_run TO erp_app;
        ELSE
            GRANT UPDATE (status) ON TABLE erp.w3_import_run TO erp_app;
        END IF;
        GRANT SELECT ON SEQUENCE
            erp.w3_private_content_id_seq,
            erp.w3_source_receipt_id_seq,
            erp.w3_source_snapshot_id_seq,
            erp.w3_import_run_id_seq,
            erp.w3_import_attempt_id_seq,
            erp.w3_source_row_id_seq
        TO erp_backup;
    END IF;
END
$$;

-- W3 0029 persistent parser/APPLY ledgers. History and parser outputs are
-- append-only. Only current-control columns and revision closure are mutable.
DO $$
BEGIN
    IF to_regclass('erp.w3_import_run_event') IS NOT NULL THEN
        REVOKE UPDATE, DELETE, TRUNCATE ON TABLE
            erp.w3_import_run_event,
            erp.w3_normalized_nhis_row,
            erp.w3_normalized_rfid_row,
            erp.w3_nhis_group,
            erp.w3_nhis_group_member,
            erp.w3_match_decision,
            erp.w3_apply_control,
            erp.w3_actual_work_revision,
            erp.w3_manual_supplement_event,
            erp.w3_plan_adjustment_event
        FROM erp_app;
        GRANT UPDATE (active_snapshot_id, active_import_run_id, row_version)
            ON TABLE erp.w3_apply_control TO erp_app;
        GRANT UPDATE (updated_by_account_id, updated_at_utc)
            ON TABLE erp.w3_apply_control TO erp_app;
        GRANT UPDATE (superseded_at_utc)
            ON TABLE erp.w3_actual_work_revision TO erp_app;
        GRANT SELECT ON SEQUENCE
            erp.w3_import_run_event_id_seq,
            erp.w3_normalized_nhis_row_id_seq,
            erp.w3_normalized_rfid_row_id_seq,
            erp.w3_nhis_group_id_seq,
            erp.w3_nhis_group_member_id_seq,
            erp.w3_match_decision_id_seq,
            erp.w3_actual_work_revision_id_seq,
            erp.w3_manual_supplement_event_id_seq,
            erp.w3_plan_adjustment_event_id_seq
        TO erp_backup;
    END IF;
END
$$;

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
