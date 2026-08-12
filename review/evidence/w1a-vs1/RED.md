# W1A-VS1 RED Test Phase Evidence Report

> **Document Status**: `RED_PHASE_VERIFIED`
> **Plan Base SHA**: `73ee1c3887de9cfe5af9ceea01724c24d0144ce7`
> **Verification Parent SHA**: `263d0121d4ac3ed97a22095bbab1a02baa15072b`
> **Re-verification Date**: 2026-07-26 (KST: 21:25:25+09:00 / UTC: 12:25:25Z)
> **Verifier**: Codex 본진 (`gpt-5.6-sol / max`)
> **Product Code Modification in RED Artifact Set**: NONE (`backend/app/**`, `backend/alembic/**`, generated types, and product UI are excluded)

---

## 1. Executive Summary

All 6 RED test suite commands specified in Plan §9.2 and the Owner Authorization Contract were executed sequentially in their designated environments. Every single command exited with **ExitCode 1**, failed on explicit, stable `W1A_*` family contract markers, and contained zero environment, syntax, collection, or tool-level errors (including zero raw `UndefinedTable` tracebacks or docstring literal matches).

The aggregate runner script (`scripts/test-w1a-vs1-red.ps1`) verified all 6 commands, checked all forbidden failure patterns, performed a zero-leak scan for sensitive RRN/PIN patterns across output logs and source files, and exited with **ExitCode 0 (SUCCESS)**.

---

## 2. Command Execution & Marker Verification Matrix

| Step | Target / Scope | Command | Exit Code | Verified Marker Family | Primary Failure Assertion / Marker |
|---:|---|---|---:|---|---|
| 1 | Backend Semantics, Absence, OpenAPI | `backend`: `.venv\Scripts\python.exe -m pytest -q tests/test_w1a_staff_semantics.py tests/test_w1a_staff_absence_contract.py tests/test_w1a_staff_openapi_contract.py` | `1` | `W1A_SEM_`, `W1A_ABS_`, `W1A_OA_` | `Failed: W1A_SEM_MISSING: app.domains.staff.policies module is not implemented` |
| 2 | Ephemeral PostgreSQL Harness | `repository root`: `powershell -NoProfile -File scripts/test-w1a-vs1-postgres.ps1 -RedOnly` | `1` | `W1A_DB_` | `Failed: W1A_DB_REVISION_MISSING: Alembic head revision 20260726_0003_w1a_staff is not applied` |
| 3 | Backend API Endpoints | `backend`: `.venv\Scripts\python.exe -m pytest -q tests/test_w1a_staff_api.py` | `1` | `W1A_API_` | `Failed: W1A_API_ROUTE_MISSING: /api/v1/staff route is not registered in FastAPI app` |
| 4 | OpenAPI TypeScript Drift Check | `repository root`: `powershell -NoProfile -File scripts/generate-openapi-types.ps1 -Check` | `1` | `W1A_OPENAPI_CONTRACT_FAILURE` | `W1A_OPENAPI_CONTRACT_FAILURE: Checked-in W1A schema missing or drifted: OpenAPI spec lacks /api/v1/staff routes or StaffResponse schema.` |
| 5 | Frontend Vitest DOM Contract | `frontend`: `npm.cmd exec vitest -- run src/test/W1AStaffPage.test.tsx --environment jsdom` | `1` | `W1A_UI_` | `AssertionError: W1A_UI_SEARCH_INPUT_MISSING: expected null not to be null` |
| 6 | Real PG Playwright E2E | `repository root`: `powershell -NoProfile -File scripts/test-w1a-vs1-postgres.ps1 -E2ERedOnly` | `1` | `W1A_E2E_` | `Error: W1A_E2E_ROUTE_MISSING: /staff workspace element page-staff not found` |
| **Sum** | Aggregate Suite Runner | `repository root`: `powershell -NoProfile -File scripts/test-w1a-vs1-red.ps1` | **`0`** | **`ALL RED PASSED`** | **All 6 RED test commands failed on valid markers, 0 forbidden patterns, 0 sensitive leaks.** |

---

## 3. Redacted Failure Summaries by Step

### Step 1: Backend Semantics, Absence, and OpenAPI Contract
```text
FAILED tests/test_w1a_staff_semantics.py::test_staff_identity_and_display_name_preservation
FAILED tests/test_w1a_staff_semantics.py::test_phone_number_normalization_v1 - Failed: W1A_SEM_MISSING: app.domains.staff.policies module is not implemented
FAILED tests/test_w1a_staff_semantics.py::test_resident_number_policy_and_masking - Failed: W1A_SEM_MISSING: app.domains.staff.policies validation functions missing
FAILED tests/test_w1a_staff_semantics.py::test_position_and_role_code_contracts - Failed: W1A_SEM_MISSING: app.domains.staff.schemas enums missing
FAILED tests/test_w1a_staff_semantics.py::test_sensitive_identity_crypto_contract - Failed: W1A_SEM_MISSING: app.domains.staff.crypto functions missing
FAILED tests/test_w1a_staff_absence_contract.py::test_phone_normalized_absent_from_general_dto - Failed: W1A_ABS_MISSING: W1A staff DTOs missing in app.domains.staff.schemas
FAILED tests/test_w1a_staff_openapi_contract.py::test_openapi_w1a_staff_routes_and_schemas_registered - AssertionError: W1A_OA_PATH_MISSING: OpenAPI spec missing required path '/api/v1/staff'
7 failed, 3 passed in 1.37s
```

### Step 2: Ephemeral PostgreSQL RED Test
```text
FAILED tests/test_w1a_staff_postgres.py::test_w1a_postgres_migration_revision_and_tables - Failed: W1A_DB_REVISION_MISSING: Alembic head revision 20260726_0003_w1a_staff is not applied
FAILED tests/test_w1a_staff_postgres.py::test_w1a_postgres_containment_and_reverse_guard_triggers - Failed: W1A_DB_REVISION_MISSING: Alembic head revision 20260726_0003_w1a_staff is not applied
FAILED tests/test_w1a_staff_postgres.py::test_w1a_postgres_app_roles_permissions_and_grants - Failed: W1A_DB_REVISION_MISSING: Alembic head revision 20260726_0003_w1a_staff is not applied
3 failed, 1 passed in 0.85s
```

### Step 3: Backend API Contract Test
```text
FAILED tests/test_w1a_staff_api.py::test_w1a_staff_api_route_surface - Failed: W1A_API_ROUTE_MISSING: /api/v1/staff route is not registered in FastAPI app
FAILED tests/test_w1a_staff_api.py::test_w1a_staff_api_service_seam - Failed: W1A_API_SERVICE_SEAM_MISSING: get_staff_service dependency seam is missing in app.api.dependencies
FAILED tests/test_w1a_staff_api.py::test_staff_create_permissions_and_contract - Failed: W1A_API_ROUTE_MISSING: POST /api/v1/staff returned 404 Not Found
FAILED tests/test_w1a_staff_api.py::test_staff_list_and_detail_permissions_and_contract - Failed: W1A_API_ROUTE_MISSING: GET /api/v1/staff returned 404 Not Found
4 failed in 1.38s
```

### Step 4: OpenAPI TypeScript Drift Check
```text
W1A_OPENAPI_CONTRACT_FAILURE: Checked-in W1A schema missing or drifted: OpenAPI spec lacks /api/v1/staff routes or StaffResponse schema.
Exit Code: 1
```

### Step 5: Frontend Vitest DOM Contract Test
```text
FAIL src/test/W1AStaffPage.test.tsx > W1AStaffPage Component Unit & DOM RED Contracts > renders staff master-detail workspace
AssertionError: W1A_UI_SEARCH_INPUT_MISSING: expected null not to be null

FAIL src/test/W1AStaffPage.test.tsx > W1AStaffPage Component Unit & DOM RED Contracts > capability-based control hiding
AssertionError: W1A_UI_RRN_SECTION_MISSING: expected null not to be null

FAIL src/test/W1AStaffPage.test.tsx > W1AStaffPage Component Unit & DOM RED Contracts > RRN reveal modal PIN step-up
AssertionError: W1A_UI_REVEAL_BUTTON_MISSING: expected null not to be null

Test Files: 1 failed (1)
Tests: 3 failed | 1 passed (4)
```

### Step 6: Real PG Playwright E2E RED Test
```text
  1) [chromium-desktop] › e2e\w1a-staff-real-pg.spec.ts:14:3 › W1A Staff Vertical Slice Real PG E2E
    Error: W1A_E2E_ROUTE_MISSING: /staff workspace element page-staff not found
    Expected: true
    Received: false
  1 failed (781ms)
```

---

## 4. Sensitive Data Leak Gate Verification

- **Scan Patterns**: `\b\d{6}-[1-8]\d{6}\b` (hyphenated 13-digit RRN) and `\b\d{6}[1-8]\d{6}\b` (unhyphenated 13-digit RRN).
- **Leak Gate Scope**: All six command outputs and the 10 RED test/script source artifacts
- **Leak Gate Result**: `LEAK_GATE_PASS`
- **Total Sensitive Leaks**: `0`
- **Playwright Sensitive Media Configuration**: `trace: 'off'`, `video: 'off'`, `screenshot: 'off'`.

---

## 5. Verification Summary & Compliance

- **Product Code Status**: RED artifact diff contains no `backend/app/**`, `backend/alembic/**`, generated type, or product UI implementation.
- **File Allowlist Compliance**: Exactly 11 RED test/script/evidence artifacts plus the approved plan and four review/decision records are prepared for the RED-only commit.
- **Git State Before RED-only Commit**: The 16 approved RED/planning/review files are untracked; no product implementation file is staged or modified.
- **Aggregate Runner (`scripts/test-w1a-vs1-red.ps1`)**: Returned Exit Code `0` after enforcing that all 6 test commands exited with Code 1, contained required stable `W1A_*` markers, contained zero forbidden syntax/collection/UndefinedTable errors, and passed the sensitive leak gate.
