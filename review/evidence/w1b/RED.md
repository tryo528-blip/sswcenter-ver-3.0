# W1B-B2 RED correction evidence

Status: `RED_VALID_PENDING_REVIEW`

Assignment: `W1B-B2-RED`

Packet: `review/packets/W1B_ASSIGNMENT_PACKET_v1.0.md`

Packet status: `P0_PACKET_APPROVED / EXCLUSION_METADATA_HARNESS_REVIEW_REQUIRED`

R1 result: `R1_MARCO_RUNTIME_HARNESS_DELTA_APPROVE / P0_INTEGRATION_HOLD`

Basis branch: `wip/w1a-office-handoff`

Basis HEAD: `e204023a7277e486018f3057653fe8aebf7b7fcf`

## Changed files

Only the two authorized files were modified for this correction:

- `backend/tests/test_w1b_red.py`
- `review/evidence/w1b/RED.md`

No product code, migration, frontend, generated file, canonical document, packet, existing W1A test, or Git history was modified. All fixture values are synthetic `TEST_W1B_*` values; no real personal information is used.

## P0/R1 correction summary

- Alembic uses `ScriptDirectory` and graph edges, freezes the existing 0001~0008 chain against the basis SHA, requires exactly one W1B direct child with `down_revision=20260728_0008_w1a_staff_legacy_mapping`, and rejects branches/merges. A sole head that is W1B or its serial descendant is allowed; the PostgreSQL revision gate accepts exactly that serial chain.
- Offline fresh-upgrade separately generates and validates SQL to the exact W1B direct-child revision, then separately validates `head` compatibility. Both paths require all five W1B tables, including `recipient_legacy_mapping`.
- SQLAlchemy metadata requires a single two-column `ForeignKeyConstraint` pairing `(recipient_id, guardian_id)` to `(recipient_guardian.recipient_id, recipient_guardian.id)`; two independent FKs cannot pass. It also requires nullable `recipient_no`, its single-column unique constraint, nullable legacy keys, and `legacy_attachment_key`. The real-PG test verifies `NULL` rows, `NULL→value`, duplicate rejection, and value/NULL immutability.
- PostgreSQL checks exercise `[start,end+1)`: primary and payer same-day overlap rejection, next-day adjacency acceptance, open-ended conflict, reverse range rejection, and invalidated-row reuse. Two independent PG connections synchronized by a barrier must produce exactly one primary-period success and one conflict.
- The representative race now uses the same recipient, two distinct guardians, and two non-identical overlapping periods. The live catalog must identify one `contype='x'` constraint with `&&` and `invalidated_at_utc IS NULL`; the losing transaction must be SQLSTATE `23P01` with that catalog constraint name, so duplicate-UNIQUE rejection cannot satisfy the race.
- PG17 catalog correction: `_period_exclusion_catalog_names` joins `c.conindid = i.indexrelid` and reads the active predicate through `pg_get_expr(i.indpred, i.indrelid)`; `pg_constraint.conbin` is not used for exclusion predicates. The `contype='x'`, `&&`, recipient/period structure, and exactly-one constraint-name checks remain required.
- The PG test hashes payer snapshot fields and compares the hash, fields, and `row_version` before/after guardian/primary changes; it also queries trigger/function definitions to fail on payer autosynchronization.
- OpenAPI is checked per operation and schema. Both history resources require POST `/{id}/invalidate` and `/{id}/replacements`; each response must expose `invalidated_at_utc` and replacement linkage. Payer request and response closures reject `payer_type`, `guardian_id`, `SELF`, and `PRIMARY_GUARDIAN` as keys or enum/value data.
- After the structural OpenAPI gate, a separate test runs `powershell -NoProfile -File scripts/generate-openapi-types.ps1 -Check`; API absence therefore produces an API named marker before any generator/environment failure. The checked-in generated TypeScript file is never edited.
- Actual API requests verify unauthenticated `401`, no-permission `403`, ADMIN inheritance, VIEW GET success, VIEW mutation `403`, MANAGE plus CSRF, expected `row_version`, stale `409` with `ROW_VERSION_CONFLICT`, and validation `422`. Nested guardian/payer/period paths must perform real HTTP create/readback, conflict codes, nested ACL/CSRF, and invalidate/replacement row-version lifecycles against PostgreSQL rows. Recipient postal/address/home/mobile values are submitted and checked independently in list/detail and the DB. A temporary trigger places dedicated synthetic name/address/home/mobile values from `NEW` into exception `DETAIL`; the request must return `500` with `UNEXPECTED_SERVER_ERROR`, while response and `caplog` message, `exc_text`, formatted `record.exc_info`, and stack surfaces reject all canaries and SQL/trace/driver/constraint information.
- History lifecycle is fail-closed against ignored versions: primary and payer existing-row replacements each receive `current_row_version + 1000` and must return HTTP `409` with `ROW_VERSION_CONFLICT`; exact-ID PG readback verifies the original `invalidated_at_utc`, replacement linkage, and `row_version` are unchanged and the recipient-scoped row-ID count/set has no new replacement. After the normal replacement, each new primary/payer row receives the same wrong version on invalidate and must remain active with an unchanged exact-ID row and row-version before the normal invalidate proceeds. Stale responses also pass the safe-response assertion.
- History action request schemas require `expected_row_version` on both invalidate/replacements POST operations.
- REC-02 follows the fixed W1A convention at `app.domains.recipient.legacy_import` (`prepare`, `apply`, `invalidate_mapping`, `replace_mapping`) and passes the standard `rows`, `active_legacy_recipient_keys`, and `active_legacy_attachment_keys` inputs. It calls real operations with synthetic recipient-key and attachment-only fixtures, verifies source-labelled `source_memo` storage, active uniqueness, same-source/original-key replacement, original-key invalidation, and public OpenAPI absence. After replacement, old is fetched by the exact captured original mapping ID and new by the old row's exact replacement ID; no unqualified source/key `.first()` lookup can pass. Token presence alone cannot pass.
- The direct-revision migration gate creates a fresh UUID-named test-only PostgreSQL cluster/database, upgrades only to the exact W1B direct child, inspects the isolated catalog for all W1B tables, columns/nullability, FKs/composite FK, CHECK, unique, exclusion, replacement linkage, and recipient-number trigger contracts, then upgrades that same isolated database to `head` and checks descendant compatibility. It never downgrades or reuses an existing development/operational database; missing tooling or cleanup fails by named harness marker.
- `W1-REC-03` remains partial-only: recipient number nullable/unique/immutable guards are covered, while issuance competition and full rollback remain `NOT_RUN / DEFERRED_TO_W1D`. `W1-SIG-01` full remains `NOT_RUN / DEFERRED_TO_W1D`; neither is represented as PASS or SKIP. ABS passes are separate and do not count as overall GREEN.

## Marco round 1 correction closure

- Valid recipient create/update, guardian create/update, primary-period create/invalidate/replacement, and payer create/invalidate/replacement now bind audit rows to the exact actor, entity, entity ID, API origin, and relevant before/after row-version fields. The RED requires meaningful create/update/invalidate/replace action semantics but does not invent or freeze an unapproved full `action_code` string.
- Guardian OpenAPI now requires collection plus item detail/update operations. The real API lifecycle verifies name-only creation, nullable phone/address/relationship fields, update with `expected_row_version`, list/detail/response/PG roundtrip, row-version progression, and audit append.
- The nested read matrix covers guardian, primary-period, and payer collection/item paths for no-permission `403` and `RECIPIENT_VIEW` success. The mutation matrix covers recipient create/update, guardian create/update, primary create/invalidate/replacement, and payer create/invalidate/replacement for unauthenticated `401`, no-permission and VIEW `403`, missing CSRF `403`, exact-row/row-set immutability, and zero audit mutation.
- OpenAPI mutation operations require stable `401/403/409/422/500` error-envelope schemas. Existing-row mutations require `expected_row_version` as both a schema property and a required field; collection-create request properties must omit it completely. Runtime missing/stale-version checks cover recipient, guardian, primary history actions, and payer history actions with exact PostgreSQL and audit non-mutation.
- Valid primary and payer replacements require the original ID set plus exactly one new ID, exact requested fields, original-row preservation plus invalidation/linkage, a fresh active replacement row, row-version progression, and audit evidence. The payer replacement response's single linkage ID must identify a contained new row with exact populated fields and `row_version=1`, while the response also exposes the original invalidation timestamp. Payer values are checked independently across API response, list/detail, PostgreSQL, and subsequent guardian/primary mutations.
- REC-02 now requires active attachment-key uniqueness in metadata/catalog, duplicate rejection during prepare/apply, and direct PostgreSQL duplicate rejection in addition to the existing recipient-key mapping lifecycle and public-absence checks.

## Grok round 2 first-audit correction

- Grok round 2 initially returned `D1_GROK_ROUND2_REQUIRED_CHANGES` for one confirmed self-contradictory assertion: after a valid payer replacement had correctly invalidated and versioned the original payer row, the test re-read that same row and required equality with its pre-replacement snapshot.
- P0 removed only that redundant post-payer-replacement equality block. The earlier payer-independence assertions after guardian and primary mutations remain, as do all exact payer replacement row-set, field, linkage, row-version, and audit assertions.
- Post-correction reproduction remained `11 collected`, `8` intended product-absence RED, `3` separate ABS pass, skip/error `0`, and Ruff clean. Grok's exact-hash re-audit returned `D1_GROK_ROUND2_APPROVE`; Marco then reviewed the same five hashes.

## Marco round 2 correction closure

- Marco round 2 returned `R1_MARCO_ROUND2_REQUIRED_CHANGES` with four confirmed false-green gaps. This correction changes only the backend RED and this evidence file; product paths remain locked.
- The payer lifecycle now performs a real name-only create by omitting phone, address, and relationship. Response, list, detail, and PostgreSQL must each expose those three fields as exact nulls. The later replacement lifecycle retains populated synthetic values and exact response/row/audit roundtrip.
- Recipient update now requires the response and PostgreSQL `row_version` to equal the prior version plus exactly one. Before the stale PATCH, the exact row, complete recipient ID set, entity audit rows, and complete audit table are captured; every surface must remain value-identical after the rejected request.
- The read ACL matrix now covers recipient collection/item and guardian/primary/payer collection/item paths for anonymous `401`, no-permission `403`, and VIEW, MANAGE, and ADMIN `200`. The rejected mutation matrix snapshots and compares the complete audit table, so an unauthorized create cannot hide an audit row under a new entity ID.
- Every mutation operation's OpenAPI `401/403/409/422/500` schema must mark the canonical outer `error`, `field_errors`, `details`, and `request_id` fields as required, and must also mark nested `error.code` and `error.message` as required.
- P0 post-correction validation is unchanged in shape: Ruff exit `0`; collection exit `0` with `11` tests; actual RED exit `1` with `8` intended product-absence failures, `3` separate ABS passes, and skip/error `0`. The first marker remains `W1B_MIGRATION_MISSING`.

## Marco round 2 re-review correction closure

- Marco's exact-hash re-review returned `R1_MARCO_ROUND2_REQUIRED_CHANGES` for two remaining false-green paths: a payer replacement response containing only a replacement ID could pass while exact populated response fields were checked only in PostgreSQL/audit, and a collection-create OpenAPI schema could expose optional `expected_row_version` because the structural gate inspected only the schema's required set.
- The payer replacement lifecycle now parses the runtime JSON response, follows its single replacement linkage ID to the exact contained new row, and requires the populated name/phone/address/relationship/dates plus `row_version=1`. The same response must expose a non-empty original invalidation timestamp before the existing exact PostgreSQL active-row, row-set, linkage, version, and audit assertions run.
- `_assert_w1b_operation_matrix` now resolves both request properties and required fields. Collection creates reject `expected_row_version` anywhere in properties; existing-row mutations require it in both properties and required. A complete in-memory W1B operation-matrix control passes without the create property and fails closed when the property is added as optional.
- P0 post-correction validation: collection exit `0` with `11` tests; Ruff exit `0`; actual RED exit `1` with `8` intended product-absence failures, `3` separate ABS passes, skip/error `0`; the optional-version negative control exit `0` with `COLLECTION_CREATE_OPTIONAL_VERSION_REJECTED`. The first RED marker remains `W1B_MIGRATION_MISSING`.

## B1 runtime-reachability harness correction

- Grok and Marco approved the preceding exact five hashes and Regina issued `P0_RED_APPROVE / RED_VALID_PENDING_PRODUCT`. When the authorized B1 writer added the schema-qualified `erp` ORM tables and ran the metadata gate, previously masked Python control-flow defects became reachable: `_table()` used `metadata.tables.get("erp.<name>") or ...` and the active-unique/exclusion helpers used SQLAlchemy clause objects in `where or ""`; each attempted boolean evaluation of a present SQLAlchemy `Table` or `TextClause` and raised `TypeError: Boolean value of this clause is not defined`.
- P0 stopped B1 in place before further implementation. The B1 product files remain preserved and are not part of this correction. The RED helper now reads the schema-qualified key first and falls back to the unqualified key only after an explicit `is None` check. No contract, table name, assertion, marker, permission, API shape, or expected result changed.
- The correction makes the already-approved metadata assertions executable for the canonical `Base.metadata = MetaData(schema="erp")` and SQLAlchemy PostgreSQL partial-index/exclusion expressions: each fallback now uses an explicit `is None` check. It does not permit a product workaround that drops the `erp` schema or weakens an active predicate. The exact backend RED/evidence delta requires a narrow Grok then Marco read-only re-review before B1 resumes.
- Grok returned `D1_GROK_RUNTIME_HARNESS_DELTA_APPROVE`, and Marco returned `R1_MARCO_RUNTIME_HARNESS_DELTA_APPROVE`; however, P0 held re-authorization after inspecting Marco's adversarial control. SQLAlchemy `2.0.51` `ExcludeConstraint` exposes its constrained columns through `columns` and its operator mapping through `operators`, not an `elements` attribute. Marco's first faithful object failed the helper, while its reported passing control added a synthetic `constraint.elements` attribute at runtime. The paused B1 model's two canonical exclusions likewise expose `columns=["recipient_id", "effective_period"]`, operators `{"recipient_id": "=", "effective_period": "&&"}`, and the active predicate, so the observed `W1B_POSTGRES_EXCLUSION_MISSING` was a harness false negative rather than a confirmed product defect.
- P0 replaced only the unreachable `elements` lookup with SQLAlchemy's actual `columns` and `operators` metadata. The existing recipient, period-form, `&&`, and `invalidated_at_utc IS NULL` requirements remain unchanged. B1 stays paused until the new exact hash passes narrow Grok and Marco review.
- P0 post-correction validation: collection exit `0` with `11` tests; Ruff exit `0`; the focused metadata gate now exits `0` with `1 passed`; and an actual, unmodified SQLAlchemy `ExcludeConstraint` control accepts the canonical shape while rejecting absent/wrong predicates, recipient, period, and operator (exit `0`, `W1B_EXCLUSION_ACTUAL_METADATA_CONTROL_OK`). The scoped diff check exits `0`.

## R1 coverage locations

- A 기간/동시성/독립성: `_assert_period_exclusion`, `_period_exclusion_catalog_names`, `_is_named_exclusion_violation`, `_run_primary_race`, and `test_w1b_04_actual_postgres_period_boundaries_are_fixed`.
- B REC-02 W1A parity: `_load_recipient_import_operations`, `_import_row`, deterministic `_mapping_row`, and `test_w1b_06_rec02_actual_synthetic_import_mapping_lifecycle_is_fixed`.
- C ACL/충돌/감사/누출: `_nested_item_paths`, `_assert_w1b_operation_matrix`, `_assert_single_audit_event`, `_real_api`, `_history_replacement_payload`, `_install_constraint_failure_trigger`, `_assert_safe_logs`, and `test_w1b_05_actual_api_acl_csrf_version_and_safe_errors_are_fixed`.
- D migration/REC-03 partial: `_run_offline_upgrade`, `_run_fresh_postgres_catalog`, `_fresh_w1b_catalog_contract`, `_has_single_column_unique`, and the recipient-number assertions in `test_w1b_04_actual_postgres_period_boundaries_are_fixed`.

## P0 first live-PG reachability correction after B1

- P0 ran the implemented W1B backend against a UUID-isolated PostgreSQL 17 cluster. The first valid focused run reached nine sealed gates and returned `7 passed / 2 failed`; the cluster database and listener were then stopped and the exact TEMP root was removed.
- The period failure was a harness-only date collision. The test first inserted an active open-ended primary period beginning `2031-01-01`, then attempted to insert the row intended for the invalidation/reuse check at `2033-01-01..2033-01-03`. The database correctly rejected that row under the approved active exclusion. Only that invalidation/reuse fixture was moved to the otherwise unused `2028-01-01..2028-01-03` interval; the same overlap, invalidation, and reuse assertions remain unchanged.
- The same active open-ended row also pre-conflicted with both representative race rows at `2050`, yielding two correct exclusion conflicts before the intended two-connection race could occur. Only the isolated race dates were moved to the otherwise unused overlapping `2027` interval; distinct connections, distinct guardians, one-success/one-`23P01` result, and catalog constraint-name checks are unchanged.
- The fresh-cluster helper created its synthetic `SSWCENTER_DATA_ROOT` at a leaf named `runtime`, while the test settings fail closed unless that leaf starts with `sswcenter-`. It also asked Windows `initdb` to create a missing `data` child, which fails before command execution in this environment. The synthetic leaf is now `sswcenter-w1b-red-runtime` and the already-validated test-only cluster root explicitly creates its `data` child before `initdb`; database target, direct-child/head upgrades, catalog assertions, and cleanup rules are unchanged.
- A faithful retry showed that Windows `pg_ctl start` succeeded and opened the isolated listener, but its postgres child inherited the `capture_output` pipe. Python therefore waited for pipe EOF until the 90-second timeout even though `pg_ctl` had exited. The PostgreSQL utility wrapper now connects stdin/stdout/stderr to `DEVNULL`; exit codes and timeouts remain mandatory, while the long-lived server can no longer retain a captured pipe.
- The payer invalidation/reuse fixture had the same ordering defect as the primary fixture: an active open-ended payer beginning `2041-01-01` pre-conflicted with the later `2043` row. Only that fixture was moved to the otherwise unused `2039-01-01..2039-01-03` interval. Payer overlap, open-ended conflict, invalidation, and exact reuse assertions remain unchanged.
- The other live-PG failure is not covered by this harness correction: the validation `422` response exposed the unknown synthetic canary field name through `field_errors`. It remains a B1 product defect candidate and product write stays paused until this exact RED/evidence correction is independently re-reviewed.

## P0 full-backend log reachability correction

- After B1 removed the validation `422` canary reflection, P0 reran that focused live-PostgreSQL gate successfully (`1 passed`). P0 then ran all ten backend gates other than the F1-dependent generated-TypeScript check in one UUID-isolated PostgreSQL 17 cluster. The database postcheck returned `W1B_DB_POSTCHECK_OK`; nine tests passed, while the API gate reached the forced-500 log assertion and failed on the transport client's routine `HTTP/1.1 500 Internal Server Error` status phrase.
- The matching forbidden term was exactly `internal server error` in an `httpx` request-summary record. It was not an application exception message, traceback, SQL/driver/constraint detail, request body, or synthetic canary. The same API gate can pass in isolation depending on when the transport summary reaches `caplog`, so accepting or rejecting the product based on that record is order/timing dependent.
- `_assert_safe_logs` now replaces only that reason phrase when the record is from the `httpx` logger, begins with `HTTP Request:`, and contains an HTTP 500 response. The logger name, request URL, status code, all other record text, `exc_text`, formatted `exc_info`, stack information, and every synthetic-canary search remain in the scan. An application or other logger that emits `Internal Server Error` still fails, and a canary in an `httpx` request summary still fails.
- This is a sealed-test/evidence correction only. No product, migration, frontend, generated contract, API requirement, marker, permission, PostgreSQL assertion, or expected outcome changes. The exact new hashes require narrow Grok and Marco review before the full backend gate is rerun.
- P0's post-correction control accepted only the exact transport status record and rejected application-log, non-request `httpx`, and URL-canary controls. Ruff and collection remained clean (`11 collected`). A new UUID-isolated PostgreSQL 17 run then applied migration `20260730_0009_w1b_recipient`, passed all ten backend gates other than the separately deselected F1 generated-TypeScript check (`10 passed, 1 deselected`), returned `W1B_DB_POSTCHECK_OK`, and exited `0` for migration, pytest, postcheck, and cleanup. The server stopped with listener/process count `0`, and the exact TEMP root was removed.

## R1 3차 4차 봉인 상태

- R1-1 대표 race는 두 독립 backend PID, 동일 recipient, 서로 다른 guardian, 서로 다르고 겹치는 두 기간을 사용한다. 두 결과 중 하나만 `success`, 나머지는 catalog에서 찾은 exclusion constraint의 SQLSTATE `23P01` conflict여야 한다.
- R1-2 forced 500은 전용 합성 name/address/home/mobile 값을 실제 create `NEW`에 넣고, test-only trigger `DETAIL`에 동적으로 포함한다. 설치·정리 실패는 named harness failure이며, response와 `caplog`의 message/`exc_text`/formatted `exc_info`/stack을 fail-close 검사한다.
- R1-3 REC-02 old mapping은 캡처한 `first_mapping_id`, new mapping은 old의 exact replacement ID로만 읽는다. source/key lookup은 active 조건 또는 exact ID와 유일성 검사를 요구한다.
- R1-4 `_run_fresh_postgres_catalog`은 UUID test-only cluster/database에서 direct revision catalog과 같은 DB의 head compatibility를 분리 검사하며 기존 DB downgrade/reuse를 하지 않는다.
- R1-5 실제 API gate는 선택 연락처 list/detail/PG readback, guardian/payer name-only lifecycle, primary/payer conflict code, nested ACL/CSRF, 두 history resource의 replacement/invalidate row-version lifecycle을 포함한다.

## Commands and results

Backend environment: `.venv\Scripts\python.exe` with `cwd=backend`; pytest configuration is `backend/pyproject.toml` with `pythonpath=["."]` and `testpaths=["tests"]`.

Collection-only:

```text
.venv\Scripts\python.exe -m pytest tests/test_w1b_red.py --collect-only -q
```

Exit: `0`

Result: `11 collected`, collection errors `0`

Actual RED:

```text
.venv\Scripts\python.exe -m pytest tests/test_w1b_red.py -q --tb=line
```

Exit: `1`

Result: passed `3`, failed `8`, skipped `0`, errors `0`

Static quality:

```text
.venv\Scripts\python.exe -m ruff check tests/test_w1b_red.py
```

Exit: `0`; `All checks passed!`

Allowed-file diff check:

```text
git diff --check -- backend/tests/test_w1b_red.py review/evidence/w1b/RED.md
```

Exit: `0`

Trailing-whitespace check was run against every untracked file reported by `git status --short`; no trailing-whitespace matches were found.

## First named marker and RED failures

First named marker:

```text
W1B_MIGRATION_MISSING: exactly one new W1B revision after 20260728_0008_w1a_staff_legacy_mapping is required
```

Observed product-absence markers:

- `W1B_MIGRATION_MISSING`
- `W1B_RECIPIENT_MODEL_MISSING`
- `W1B_RECIPIENT_API_MISSING`

The generated-contract test also stops at `W1B_RECIPIENT_API_MISSING` because its required structural API gate is absent; it does not hide that RED behind a generator or environment error. The three passing tests are ABS/leak self-test checks only. They are not overall GREEN and do not establish W1B implementation completion.

## Product diff and Git status

Tracked product diff check:

```text
git diff --name-only HEAD -- backend/app backend/alembic frontend/src ":(exclude)frontend/src/test"
```

Result: `PRODUCT_DIFF=0`

The exact requested status command was also run:

```text
git status --short
```

No commit, push, reset, checkout, rebase, stash, or history operation was performed. Frontend results were not inspected or estimated by B2. Any other untracked frontend/packet artifacts shown by Git remain untouched and outside B2 authority.

## Remaining blockers

1. W1B migration, recipient metadata/domain/router, operation schemas, PostgreSQL tables/constraints, actual API behavior, generated contract, and REC-02 importer are absent at the basis HEAD.
2. Live PG boundary, API, log-leak, generated-contract, and importer checks are gated behind the missing W1B product surface; they fail by named marker rather than skip/error.
3. `W1-REC-03` full and `W1-SIG-01` full remain `NOT_RUN / DEFERRED_TO_W1D`.
4. Frontend work is outside B2 scope; no frontend result is claimed.

Next step: Grok and Marco narrow exact-hash review of the ExcludeConstraint metadata correction, then Regina re-authorizes the paused B1 writer. After product implementation, rerun this RED at an exact clean SHA before focused GREEN.
