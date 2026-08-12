# W1D 서비스계약·인정 전환 상세 작업계획

> 문서 상태: `PHASE1_DESIGN_RED_DRAFT`
>
> 작성일: 2026-07-30 KST
>
> 기준 branch: `codex/w1d-contract-transition`
>
> 기준 SHA: `266beeaa2d150371ccd1a0f26f69249eca86ba16`
>
> 직전 gate: `W1C_PASS`
>
> W1C 승인 후보: `a86567fe5c3b88bc9148c04b97f3626e0972ed75`
> (`MARCO_W1C_REVIEW_RESULT=APPROVE` → 레지나 `W1C_PASS`)
>
> 패킷: `review/packets/W1D_ASSIGNMENT_PACKET_v1.0.md`
>
> 현재 승인 범위: 설계·계약 초안 + 실행 가능한 RED (제품 구현 미승인)
>
> 단일 writer: Grok

## 1. 권위와 목표

이 계획은 다음 정본의 서비스계약·최초 계약 수급자번호 발급·계약서명자
snapshot·인정 전환 계약만 하나의 W1D 경계로 고정한다.

| 영역 | 정본 |
|---|---|
| 업무 | `02#fr-certification-transition` §6, `02#fr-contract` §7 |
| W1B 승계 | `02` §4.1 수급자번호, §4.4 계약서명자 snapshot |
| UI·API | `03#ui-contract` §5 |
| 수급자 표시 | `03` §4.1~4.2 최초 계약 전 번호 nullable |
| DB | `04#db-contract` §8, `04` §10 인정 전환 transaction |
| W1B DB 승계 | `04` §4.1 수급자번호, §5 계약서명자 snapshot |
| 로드맵 | `06` §1·§2 W1D 행 |
| 운영 | AI 운영정본 v3.5 HIGH·exact SHA·독립검수 |
| matrix | `W1-REC-03`, `W1-SIG-01`, `W1-CON-01`~`04`, `W1-TRN-01`~`04`, `W1-ABS-08`~`10` |

목표는 W1C PASS 위에 다음을 **하나의 transaction 경계와 하나의 UI 흐름**으로
설계·RED 고정하는 것이다. W1E 배정·Wave 2 일정/업무카드는 비범위다.

1. 서비스별 독립 계약과 계약기간 불변조건
2. 최초 계약 확정 transaction 안의 수급자번호 1회 원자 발급
3. 계약 당시 독립 서명자 snapshot
4. 인정 전환 preview와 명시 확인
5. stale hash 재검산과 관련 행 잠금
6. 영향 서비스 multiset과 대체계약의 완전성
7. 기존 인정·등급·장기요양 계약 종료와 새 인정·등급·계약 생성의 단일 transaction
8. 성공·실패·rollback·감사·UI 상태의 일치

## 2. 설계 확정 제안 (구현 전 감사 대상)

아래 10항목은 패킷 §6 필수 확정 항목이다. 오푸스/요셉 감사와 레지나 재봉인
전에는 제품 코드에 반영하지 않는다.

### 2.1 API resource path와 operation 이름

수급자 scoped 계약 원장 (W1B/W1C nested 패턴 계승):

| Method | Path | OperationId | 권한 |
|---|---|---|---|
| `GET` | `/api/v1/recipients/{recipient_id}/contracts` | `listRecipientContracts` | `RECIPIENT_VIEW` 또는 ADMIN |
| `POST` | `/api/v1/recipients/{recipient_id}/contracts` | `createRecipientContract` | `RECIPIENT_MANAGE` 또는 ADMIN |
| `GET` | `/api/v1/recipients/{recipient_id}/contracts/{contract_id}` | `getRecipientContract` | `RECIPIENT_VIEW` 또는 ADMIN |
| `POST` | `/api/v1/recipients/{recipient_id}/contracts/{contract_id}/end` | `endRecipientContract` | `RECIPIENT_MANAGE` 또는 ADMIN |

인정 전환 (별도 named operation, preview/apply 분리):

| Method | Path | OperationId | 권한 |
|---|---|---|---|
| `POST` | `/api/v1/recipients/{recipient_id}/certification-transitions/preview` | `previewCertificationTransition` | `RECIPIENT_MANAGE` 또는 ADMIN |
| `POST` | `/api/v1/recipients/{recipient_id}/certification-transitions/apply` | `applyCertificationTransition` | `RECIPIENT_MANAGE` 또는 ADMIN |

명시적 부재:

- reactivate / reopen / restore operation 없음
- `contract_no` path·query·body 필드 없음
- 종료 계약을 PATCH로 active로 되돌리는 operation 없음
- 서비스 카탈로그 CRUD 없음 (기존 seed 조회만 재사용 가능)

### 2.2 Request/Response schema

**ContractCreateRequest**

| 필드 | 필수 | 규칙 |
|---|---|---|
| `service_type_code` | 필수 | seed 코드: `HOME_CARE`, `HOME_BATH`, `TEMP_HOME_CARE`, `HOSPITAL_ESCORT`, `BARO_CARE` |
| `start_date` | 필수 | `date` |
| `end_date` | 선택 | `date` 또는 null; `start_date > end_date`면 422 |
| `service_start_date` | 선택 | 급여개시일; null 허용, 누락 차단 없음 |
| `signer_name` | 선택 | nullable snapshot |
| `signer_relationship_text` | 선택 | nullable snapshot |
| `signer_phone` | 선택 | nullable snapshot |
| `end_reason_text` | 선택 | 자유 문자열; 생성 시에도 null 허용 |

**ContractEndRequest**

| 필드 | 필수 | 규칙 |
|---|---|---|
| `expected_row_version` | 필수 | stale 409 |
| `end_date` | 필수 | 종료일; open-ended 계약을 closed로 전환 |
| `end_reason_text` | 선택 | 자유 문자열 null 허용 |

**ContractResponse / ContractListResponse**

- `id`, `recipient_id`, `service_type_code`, `service_group_code`
- `start_date`, `end_date`, `service_start_date`
- `signer_name`, `signer_relationship_text`, `signer_phone`
- `end_reason_text`
- `invalidated_at_utc`, `replacement_contract_id` (null 가능; history 계승)
- `row_version`
- **금지 property**: `contract_no`, `contract_sequence`, `signer_guardian_id`,
  `signer_payer_id`, `signer_birth_date`, `signer_address`, `end_reason_code`,
  `discharge_date`

**CertificationTransitionPreviewRequest**

| 필드 | 필수 | 규칙 |
|---|---|---|
| `new_start_date` | 필수 | 새 인정 시작일 |
| `new_end_date` | 필수 | 새 인정 종료일; 정본 04 §6.2의 NOT NULL 기간과 일치 |
| `new_grade_code` | 필수 | `"1"`~`"5"` |
| `new_grade_start_date` | 필수 | 인정기간 안 |
| `new_grade_end_date` | 필수 | 등급 종료일; 새 인정기간 안의 유한 기간 |
| `replacement_contracts` | 필수 | 영향 LTC 서비스 multiset과 1:1 대응 item 배열 (0개 허용은 영향 0일 때만) |

새 인정·등급 종료일은 생략 또는 `null`을 허용하지 않으며 서비스가 임의 기본
기간을 합성하지 않는다. 계약 대체행의 종료일 nullable 규칙과 혼동하지 않는다.

`replacement_contracts[]` item:

| 필드 | 필수 |
|---|---|
| `ended_contract_id` | 필수 |
| `service_type_code` | 필수 (ended와 동일 서비스) |
| `start_date` | 필수 (`new_start_date`와 일치 권장·검사) |
| `end_date` | 선택 |
| `service_start_date` | 선택 |
| `signer_name` / `signer_relationship_text` / `signer_phone` | 선택 |
| `end_reason_text` | 선택 (새 계약 쪽; 종료 사유는 시스템 제안 가능) |

**CertificationTransitionPreviewResponse** (all fields **required**; R10-02)

| 필드 | 의미 |
|---|---|
| `preview_token` | opaque token (아래 §2.3) |
| `canonical_hash` | exact 64-lower-hex; **equals** `token.preview_hash` |
| `serialization_version` | exact `"w1d-transition-v1"` |
| `proposed_end_date` | `new_start_date - 1 day` |
| `affected_certification_period_ids` | 종료 대상 인정기간 |
| `affected_grade_period_ids` | 종료 대상 등급기간 |
| `affected_contract_ids` | 종료 대상 장기요양 계약 |
| `service_multiset` | 영향 서비스 코드 multiset (정렬 고정) |
| `replacement_preview` | 대체계약 요약 |

Runtime RED reads **`preview.canonical_hash` only** — never a non-contract
`preview_hash` response attribute. Missing `canonical_hash` is product RED.

**CertificationTransitionApplyRequest**

| 필드 | 필수 key | nullability | 규칙 |
|---|---|---|---|
| `preview_token` | **required key** | **nullable** (`str \| null`) | key 생략 → schema `VALIDATION_ERROR`. explicit `null` 또는 `""`(blank) → service `CERTIFICATION_TRANSITION_PREVIEW_REQUIRED`. 비공백 문자열만 token 검증 단계로 진행 |
| `confirmed` | 필수 | non-null bool | `true`만 통과; false/누락 → 422 confirmation |
| `replacement_contracts` | 필수 | array | token.bound_replacements 와 exact |

**CertificationTransitionApplyResponse**

| 필드 | 의미 |
|---|---|
| `recipient_id` | 대상 |
| `ended_certification_period_ids` | 종료된 인정 |
| `ended_grade_period_ids` | 종료된 등급 |
| `ended_contract_ids` | 종료된 계약 |
| `new_certification_period_id` | 새 인정 |
| `new_grade_period_id` | 새 등급 |
| `new_contract_ids` | 새 계약 목록 |
| `audit_correlation_id` | **UUID string** = `audit_event.request_id` 와 1:1 동일 (event bigint id 아님) |
| `recipient_no` | 발급 후 번호 (전환 중 신규 발급은 없음; 계약 생성 경로만 발급) |

**certification_number=null 전환 (단일 안정 코드 봉인):**

- preview/apply 모두 exact `404` + `CERTIFICATION_IDENTITY_NOT_FOUND`
  (W1C identity 부재 코드 재사용; “또는 동등” 문구 폐기).

### 2.3 preview/apply token, canonical preview_hash vs signed replacement intent (B2)

Opus W1D-B2 봉인: **canonical preview_hash** (DB + signed non-sensitive replacement
subset) 와 **token.bound_replacements** (full exact, including PII free-text) 를 분리한다.
요청 replacement 전체를 preview_hash 입력에 넣으면 빈 배열이 409
`CERTIFICATION_TRANSITION_STALE` 이 되어 422 MISMATCH와 충돌한다.

- `serialization_version`: 고정 문자열 `w1d-transition-v1`
- preview는 **DB write 0건**
- token HMAC 키: 전용 `SSWCENTER_TRANSITION_TOKEN_KEY` (CSRF/pin/app secret 재사용 금지;
  구현감사에서 분리 재확인)
- token TTL: 30분 (`exp` unix seconds). 시계 seam:
  `app.domains.w1d.clock.now_utc()` (테스트에서 injectable)

**Apply 검증 선행순위 (고정, 첫 위반에서 중단, write 0):**

```text
0. request schema parse (Pydantic)
     - preview_token key 생략 → 422 VALIDATION_ERROR (field_errors)
     - confirmed/replacement_contracts schema 위반 → 422 VALIDATION_ERROR
1. confirmed === true
     else 422 CERTIFICATION_TRANSITION_CONFIRMATION_REQUIRED
2. preview_token is not null AND btrim(preview_token) <> ''
     else 422 CERTIFICATION_TRANSITION_PREVIEW_REQUIRED
     (explicit null / "" 만; key 생략은 step 0)
3. recipient 존재 검증
     else 404 RECIPIENT_NOT_FOUND
4. certification_identity 존재 검증 (W1C identity 행)
     else 404 CERTIFICATION_IDENTITY_NOT_FOUND
     **이 단계는 token HMAC 검증보다 앞선다.** null-identity apply는
     garbage/invalid token 이어도 TOKEN_INVALID 가 아니라
     CERTIFICATION_IDENTITY_NOT_FOUND 만 반환한다 (R8-08).
5. token HMAC 진위 · exp 미만 · recipient_id 일치 · serialization_version 일치
     else 422 CERTIFICATION_TRANSITION_TOKEN_INVALID
     (변조·만료·cross-recipient replay; STALE 아님)
6. 관련 행 FOR UPDATE 후 **preview_hash** 재구성 (정본 04 §10.1) →
     token.preview_hash constant-time 비교
     mismatch → 409 CERTIFICATION_TRANSITION_STALE
7. apply.replacement_contracts 가 token.bound_replacements 와 완전 일치
     else 422 CERTIFICATION_TRANSITION_REPLACEMENT_MISMATCH
8. apply 본문 (종료·생성·단일 감사)
```

**Preview 존재 검증 순서:** recipient → certification_identity → 본문.
identity 부재 시 exact `404` + `CERTIFICATION_IDENTITY_NOT_FOUND` only.

**counter 계약 (N1 봉인):**

- `RECIPIENT_NO/0` 를 DELETE/reset 하지 않는다 (테스트 포함).
- 시설 전역 monotonic; `after_sequence == before_sequence + 1` (발급 1회당).
- 최초 absent-row 경로는 **fresh isolated cluster의 첫 first-contract race** 가 담당.
  이후 테스트는 baseline-relative delta 만 단정.

**A. Canonical preview_hash (정본 04 §10.1 — J-W1D-R3-H06):**

정규 입력집합 (canonical serialization 후 SHA-256):

- 수급자 id 와 현재 인정 본번호
- 종료 대상 인정기간·관련 등급기간 (`proposed_end = new_start - 1일`에 유효한 행,
  즉 `start_date <= proposed_end <= end_date`; 방어적 legacy null end는 상한 없음;
  id ASC, row_version, dates, invalidation)
- 종료 대상 장기요양 계약 (같은 `proposed_end`에 유효한 active LTC, id ASC,
  service codes, dates, row_version)
- 각 계약의 서비스 ID multiset (정렬 코드)
- 제안 새 인정기간·등급 (new_start/end, grade_code/start/end)
- **서비스별 대체계약 입력의 non-sensitive 정규화 부분집합**
  (ended_contract_id, service_type_code, start_date, end_date, service_start_date;
  signer_name/relationship/phone/end_reason_text 는 hash 입력에서 **제외**)
- 관련 aggregate `row_version` 과 무효화·대체·`updated_at_utc` 상태
- `v` = `w1d-transition-v1`, 날짜 `YYYY-MM-DD`, null 유지, `sort_keys=True`,
  separators `(',', ':')`
- `preview_hash = SHA-256(canonical_json).hexdigest()`

민감/표시 필드(서명자 PII·end_reason_text 본문)는 hash에 넣지 않되
**token.bound_replacements** HMAC에 exact 바인딩한다.

**B. Token payload (HMAC 서명):**

```text
{
  "v": "w1d-transition-v1",
  "recipient_id": <int>,
  "exp": <unix>,
  "preview_hash": "<hex>",
  "transition": { new_start_date, new_end_date, new_grade_code, new_grade_start_date, new_grade_end_date },
  "bound_replacements": [
    {
      "ended_contract_id", "service_type_code", "start_date", "end_date",
      "service_start_date",
      "signer_name", "signer_relationship_text", "signer_phone", "end_reason_text"
    }
  ]  // ended_contract_id ASC; full fields null-exact
}
```

**Apply 비교 순서 (봉인 — identity 선행 후 token, 그 다음 preview_hash):**

1. recipient 존재 → certification_identity 존재 (404 코드 위 표)
2. token HMAC / exp / recipient / version
3. 행 FOR UPDATE
4. **현재 DB + token.bound_replacements 의 non-sensitive 정규화 부분집합** 으로
   preview_hash 재구성 → token.preview_hash constant-time 비교
   → 불일치 = 409 `CERTIFICATION_TRANSITION_STALE` (DB 또는 봉인 의도 drift)
5. request `replacement_contracts` exact vs token.bound_replacements
   → 불일치 = 422 `CERTIFICATION_TRANSITION_REPLACEMENT_MISMATCH`
6. 종료·생성·단일 감사

**전환 범위와 benefit/approval (정본 04 직접 대조):**

- `04` §10.2 apply 단계는 수급자·인정·등급·(장기요양)계약 lock → 종료 → 새
  인정·등급·서비스별 계약 → 단일 감사다. **혜택기간·승인금액 기간을 apply
  statement에 넣지 않는다.**
- 동일 수급자의 benefit/approval 행은 전환으로 자동 종료·재작성하지 않는다.

**certification_number=null recipient:** 전환 preview/apply 각각 exact
`404` + `CERTIFICATION_IDENTITY_NOT_FOUND` only (동등 코드 금지; M04).

### 2.4 권한 코드

- **신규 권한 코드 없음**. W1B 권한 재사용:
  - 조회: `RECIPIENT_VIEW` (ADMIN 상속)
  - mutation·preview·apply: `RECIPIENT_MANAGE` (ADMIN 상속)
- 미인증 401, 무권한 403, unsafe mutation CSRF 필수 (기존 Wave0/W1B 패턴).

### 2.5 안정 오류코드 (최종 문자열)

| HTTP | code | 사용 |
|---|---|---|
| 401 | `AUTHENTICATION_REQUIRED` | 미인증 (W1B/W1C 공통 exact code) |
| 403 | `PERMISSION_REQUIRED` | 무권한 (no-perm / VIEW-only mutation) |
| 403 | `CSRF_REQUIRED` | unsafe mutation CSRF 부재 |
| 404 | `RECIPIENT_NOT_FOUND` / `CONTRACT_NOT_FOUND` | 대상 없음 |
| 409 | `CONTRACT_SERVICE_PERIOD_CONFLICT` | 같은 서비스 기간 겹침 |
| 409 | `CONTRACT_SERVICE_GROUP_PERIOD_CONFLICT` | 다른 그룹 기간 겹침 |
| 409 | `CONTRACT_REACTIVATION_FORBIDDEN` | 종료 계약 재활성화 시도 |
| 409 | `ROW_VERSION_CONFLICT` | 계약 end stale version |
| 409 | `CERTIFICATION_TRANSITION_STALE` | preview 후 projection 변경 |
| 422 | `CERTIFICATION_TRANSITION_CONFIRMATION_REQUIRED` | `confirmed !== true` |
| 422 | `CERTIFICATION_TRANSITION_REPLACEMENT_MISMATCH` | multiset 누락·추가·중복·잘못된 서비스 |
| 422 | `CERTIFICATION_TRANSITION_TOKEN_INVALID` | token 만료·위조·수신자 불일치 |
| 422 | `CERTIFICATION_TRANSITION_PREVIEW_REQUIRED` | apply-only 호출 (token 없음) |
| 422 | `VALIDATION_ERROR` | 기간 역순·등급 enum·필드 형식 |
| 500 | `UNEXPECTED_SERVER_ERROR` | 내부; SQL/trace/PII 비노출 |

envelope는 기존 W1B/W1C **exact top-level** 형태만 허용 (R4-06):

```json
{
  "error": {"code": "...", "message": "..."},
  "field_errors": [],
  "details": {},
  "request_id": "<uuid>"
}
```

- `field_errors`/`details`/`request_id`는 **top-level** (error 객체 안이 아님).
- `detail` 키 완전 금지.
- `request_id`는 non-empty parseable UUID.

### 2.6 DB enforcement: 기간·그룹 overlap

**테이블 `erp.recipient_contract`** (단일 신규 테이블; catalog는 W1A seed 재사용):

| 컬럼 | 규칙 |
|---|---|
| `id` | bigint identity PK |
| `recipient_id` | FK → `recipient.id` NOT NULL |
| `service_type_id` | FK → `service_type.id` NOT NULL |
| `start_date` | NOT NULL |
| `end_date` | NULL 허용 |
| `contract_period` | generated `daterange(start_date, COALESCE(end_date,'infinity'), '[]')` 또는 half-open `[start, end+1)` — **W1B/W1C 계승 half-open `[start, end+1)` 채택** |
| `service_start_date` | NULL 허용 |
| `end_reason_text` | NULL 허용, enum/check/default 없음 |
| `signer_name`, `signer_relationship_text`, `signer_phone` | 모두 NULL |
| `invalidated_at_utc` | NULL=active |
| `replacement_contract_id` | self-FK NULL |
| actor·timestamp·`row_version` | 공통 |

**Same-service exclusion (GiST):**

```text
EXCLUDE USING gist (
  recipient_id WITH =,
  service_type_id WITH =,
  contract_period WITH &&
) WHERE (invalidated_at_utc IS NULL)
```

이름: `ex_recipient_contract_same_service_period`

**Cross-group overlap (constraint trigger, concurrency-safe — J-W1D-R2-H03):**

- 함수 `fn_recipient_contract_group_overlap()` on INSERT/UPDATE of active rows:
  1. **먼저** `SELECT id FROM erp.recipient WHERE id = NEW.recipient_id FOR UPDATE`
     (parent-row lock, 전 경로 동일 recipient → lock 순서로 deadlock 회피).
  2. 그 다음 active peer 계약을 join하여 다른 `service_group_id` 이고 period `&&`
     이면 `raise exception` / `exclusion_violation`,
     constraint name `trg_recipient_contract_group_period_overlap`.
- 같은 그룹의 다른 서비스는 통과.
- DEFERRABLE INITIALLY IMMEDIATE 허용. Advisory lock 대안은 parent-row FOR UPDATE와
  동등 직렬화만 인정.
- RAW two-connection RED: cross-group overlap → 정확히 1 commit + 1 constraint
  failure; same-group different services → 2 commit.

**Reactivation 금지 (L2 해석 봉인):**

- service layer: 종료 계약(`end_date IS NOT NULL`)을 active open-ended로 되돌리는
  연산 없음. 재이용은 새 INSERT.
- DB 방어: `end_date` non-null → null 전이 거부
  (`ck_recipient_contract_no_reactivation` 또는 equivalent trigger).
- 종료일 오타 정정(non-null → 다른 non-null)은 본 W1D 경계에서 **미제공**.
  필요 시 후속 승인된 정정 operation. 잔여위험: 오타 수정 UX 부재.

**기간 역순:** `CHECK (end_date IS NULL OR start_date <= end_date)`.

### 2.7 first-contract counter lock 순서와 deadlock 회피

기존 Wave0 테이블 `erp.business_number_counter` 재사용:

| 키 | 값 |
|---|---|
| `number_type` | `RECIPIENT_NO` |
| `number_year` | `0` (연도 비의존 시설 전역 시퀀스) |
| 발급 형식 | zero-pad 6자리 이상 십진 문자열 (`f"{sequence:06d}"`) |
| uniqueness | 기존 `uq_recipient_recipient_no` |
| immutability | 기존 `bu_recipient_no_immutable` / `fn_recipient_no_immutable` |

**Lock 순서 (모든 first-contract 경로 동일):**

```text
1. SELECT recipient WHERE id=:id FOR UPDATE
2. if recipient_no IS NULL:
     SELECT business_number_counter
       WHERE number_type='RECIPIENT_NO' AND number_year=0
       FOR UPDATE
     (없으면 INSERT last_sequence=0 후 다시 FOR UPDATE — 경쟁 시 unique 충돌 retry 1회)
3. INSERT recipient_contract ...
4. if was null: recipient_no = format(counter+1); counter.last_sequence += 1
5. audit RECIPIENT_CONTRACT_CREATE (+ RECIPIENT_NO_ASSIGN if issued)
6. COMMIT
```

- 재계약·서비스 추가: step 2/4 skip. `recipient_no` 불변.
- 두 connection 경쟁: counter row lock이 serializes 발급 → 중복 번호 불가.
- deadlock 회피: 항상 **recipient → counter** 순서. 다른 경로도 counter를 먼저
  잠그지 않는다. transition apply는 번호를 발급하지 않는다(기존 계약 전제).
- rollback: contract insert·counter 증가·recipient_no 할당이 한 transaction이므로
  전부 원복.

### 2.8 apply lock 순서, isolation, fault-injection seam (B1)

**Isolation:** PostgreSQL `READ COMMITTED` + 명시적 `SELECT ... FOR UPDATE`.

W1C `ct_recipient_certification_grade_containment` 와
`ct_recipient_grade_period_containment` 는 모두
`DEFERRABLE INITIALLY IMMEDIATE` 다. 인정기간을 먼저 줄이면 같은 statement
경계에서 아직 긴 활성 등급이 포함 위반을 낸다.

**Apply statement 순서 (봉인 — grade 먼저 종료):**

```text
1. recipient FOR UPDATE
2. certification_identity FOR UPDATE (없으면 전환 거부)
3. non-invalidated certification_periods FOR UPDATE ORDER BY id
4. non-invalidated grade_periods FOR UPDATE ORDER BY id
5. non-invalidated LONG_TERM_CARE contracts FOR UPDATE ORDER BY id
6. 잠근 집합에서 `proposed_end`에 실제 유효한 행만 종료 대상/hash 입력으로 선택;
   이미 그보다 먼저 끝난 과거 인정·등급·계약 행은 변경하지 않음
7. recompute preview_hash (DB + signed normalized replacements); compare token;
   then compare full bound replacements
8. END target grade periods first
     SET end_date = proposed_end_date (= new_start - 1 day), row_version++
     (containment: grade still inside old cert until cert ends next)
9. END target certification periods
     SET end_date = proposed_end_date, row_version++
10. END target LTC contracts
     SET end_date = proposed_end_date, end_reason_text optional system/user
11. INSERT new certification period [new_start, new_end]
12. INSERT new grade period under new cert (same or nested dates inside new cert)
13. INSERT replacement contracts (recipient_no 불변; first-contract 아님)
14. INSERT exactly one audit_event CERTIFICATION_TRANSITION_APPLY
15. COMMIT
```

연속 전환에서는 직전 새 기간만 다음 `proposed_end`의 종료 대상이 된다. 더 이른
과거 기간의 `end_date`, `row_version`, `updated_at_utc`와 감사 이력은 그대로 보존한다.

- 성공 경로 RED는 **활성 등급이 존재하는 상태**에서 apply 전체가 성공하고, 기존
  등급·인정의 `end_date` 가 각각 exact `proposed_end_date` 임을 단정한다.
- constraint deferral(`SET CONSTRAINTS ... DEFERRED`)은 **사용하지 않는다**.
  statement 순서로 IMMEDIATE trigger를 만족한다.
- benefit/approval 행은 lock·종료·생성 대상이 아니다 (§2.3).

**Fault-injection seam (테스트 전용):**

- `app.domains.w1d.fault.set_fault_point(label|None)` /
  `maybe_fault(label)`
- **transition apply** labels: `after_lock`, `after_hash`, `after_end_grade`,
  `after_end_cert`, `after_end_contracts`, `after_create_cert`,
  `after_create_grade`, `after_create_contracts`, `after_audit`, `before_commit`
- **contract create** labels: `after_contract_insert` (create path only; N1/REC-03
  atomic rollback RED)
- 각 seam 발화 시 예외 메시지/코드에 exact marker `W1D_FAULT:<label>` 포함
  (R4-04; unrelated 예외는 해당 label PASS 불가)
- clock: `app.domains.w1d.clock.set_now_utc(dt|None)` for token TTL RED
- 각 지점 예외 → 전체 rollback, 부분 성공 0
- production no-op; 환경변수 활성화 금지

**동시 apply (W1-TRN-03 / N3 / J-H02 / R4-01):**

- 결정적 lock race: 별도 **blocker** 트랜잭션이 recipient `FOR UPDATE` 보유.
- 두 apply 세션(`application_name=w1d-apply-a|b`)을 barrier 후 기동하고,
  `pg_stat_activity` 에서 **둘 다** `wait_event_type='Lock'` 관측 필수.
  미관측 시 즉시 FAIL (`W1D_TRN03_LOCK_WAIT_NOT_OBSERVED`) — soft pass 금지.
- blocker commit 후: 정확히 1 success + 1 `CERTIFICATION_TRANSITION_STALE`.
- 승자 response 파싱: non-null new certification id, new grade id, exact
  new contract id list, UUID `audit_correlation_id`.
- 해당 id로 최종 행 exact 조회; counts 1/1/expected contracts; 원본 end dates
  = proposed_end; aggregate audit 1건 `request_id` = correlation UUID.
- 패자 write 0.

**stale 대상 (각각 별도 RED):** 인정 날짜(등급 containment 유지 mutation),
등급 코드/기간, 계약 기간, **서비스 multiset 실제 변경**(예: HOME_CARE→추가
HOME_BATH 또는 서비스 교체).

### 2.9 단일 감사 event 구조와 비식별 projection (M2)

**계약 단독 create/end** (전환 밖 API; append-only `audit_event`):

| action_code | entity_type | 비고 |
|---|---|---|
| `RECIPIENT_CONTRACT_CREATE` | `RECIPIENT_CONTRACT` | 계약 id·기간·service; **signer PII 미포함** |
| `RECIPIENT_NO_ASSIGN` | `RECIPIENT` | before null / after recipient_no |
| `RECIPIENT_CONTRACT_END` | `RECIPIENT_CONTRACT` | end_date·row_version; end_reason_text **미포함** |

**인정 전환 apply — transaction 창 안에서 정확히 1건:**

| 필드 | 값 |
|---|---|
| `action_code` | `CERTIFICATION_TRANSITION_APPLY` |
| `entity_type` | `RECIPIENT` |
| `entity_pk` | `recipient_id` |
| `actor_account_id` | confirmer |
| `actor_kind` | `USER` |
| `occurred_at_utc` | apply 시각 (DB `clock_timestamp()` window: apply 직전~commit 직후 inclusive) |
| `request_id` | correlation UUID |
| `reason_code` | `USER_CONFIRMED_TRANSITION` |
| `created_from` | `API` |

**before_json / after_json 비식별 projection (봉인; R9-01):**

```text
{
  "preview_hash": "<64-lower-hex>",   // BOTH sides: authorized token.preview_hash
  "certification_periods": [
    {"id","start_date","end_date","row_version"}
  ],
  "grade_periods": [
    {"id","certification_period_id","grade_code","start_date","end_date","row_version"}
  ],
  "contracts": [
    {"id","service_type_code","service_group_code","start_date","end_date","row_version"}
  ],
  "service_multiset": ["SERVICE_CODE", ...],  // active contracts only, sorted
  "new_ids": {  // AFTER ONLY — before_json must omit this key
    "certification_period_id", "grade_period_id",
    "contract_ids": [...]  // ordered; equals apply response + persisted rows
  }
}
```

**`preview_hash` 의미 (R9-01 — 재계산 post-state digest 금지):**

1. Preview response `canonical_hash` 는 plan §2.3 정규 serializer 가 만든
   exact 64-lower-hex `token.preview_hash` 와 **동일**하다.
2. Apply 직전 성공 preview 에서 그 값을 capture 한다.
3. audit `before_json.preview_hash` 와 `after_json.preview_hash` 는 **둘 다**
   그 capture 된 authorization hash 이다. “어느 preview 가 승인됐는지” 기록이며
   after 시점 행으로 다시 hash 하지 않는다.
4. certification/grade/contracts/service_multiset/new_ids 는 독립적으로
   persisted rows 에서 구성해 JSON equality 로 검증한다.
5. 투영 helper 는 `preview_hash` 를 **필수 입력**으로 받으며 동일 이름으로
   두 번째 serializer 를 발명하지 않는다.
6. Projection 스키마는 위 키 집합만 허용한다 (`invalidated_at_utc` 미포함 —
   활성/종료 상태는 end_date·row_version 으로 표현).

**감사 append-only (R9-02):** isolated workers=1 클러스터에서 apply 직전/직후
**전체** `audit_event` 행 집합을 canonical 비교한다.

- after.length == before.length + 1
- before 의 모든 행이 id 순서·canonical JSON 동일 (mutation/deletion 0)
- 추가 1건만 exact `CERTIFICATION_TRANSITION_APPLY` aggregate (본 수급자)
- `MAX(id)` 창 또는 `id > audit_id_before` 단독 비교는 금지 (기존 행 변조를 놓침)

금지 (audit JSON canary):

```text
signer_name, signer_phone, signer_relationship_text
guardian/payer name/phone/address
end_reason_text 본문, recipient.name, 주민·주소 평문
```

- preview audit write 0
- apply 실패 시 audit 0
- 전환 transaction 창에서 `RECIPIENT_CONTRACT_CREATE` /
  `RECIPIENT_CONTRACT_END` / cert·grade 단계 audit **추가 금지**
  (aggregate 1건만). 계약 단독 API는 위 개별 action 유지.

### 2.10 다음 Alembic revision exact 이름

| 항목 | 값 |
|---|---|
| 파일명 | `backend/alembic/versions/20260730_0011_w1d_recipient_contract.py` |
| `revision` | `20260730_0011_w1d_recipient_contract` |
| `down_revision` | `20260730_0010_w1c_certification_ledgers` |
| 내용 | `recipient_contract` 테이블, generated/stored period, same-service exclusion, group-overlap trigger, no-reactivation guard, grants to `erp_app`, **신규 permission seed 없음** |
| Phase 1 | **migration 파일 생성 금지** (RED만 존재 요구) |

기존 `0001`~`0010` 바이트 불변. single head의 direct child 1개만 허용.

## 3. 모듈·UI 배치 제안 (구현 단계)

```text
backend/app/domains/w1d/
  __init__.py
  schemas.py
  policies.py          # period, multiset, canonical hash
  service.py           # contract + transition
  repository.py
  errors.py            # domain error mapping
backend/app/api/w1d.py # router include in main
frontend/src/services/w1dApi.ts
frontend/src/components/recipients/RecipientContractPanel.tsx
  (수급자 상세 workspace에 W1C panel과 병치)
```

UI 계약 (`03` §5):

- 시작일·서비스종류만 필수 표시; 종료일·급여개시일·서명자 3필드·종료사유 선택
- 계약번호 입력/필수표시 없음
- 종료사유 초기 value 빈 문자열; datalist 제안 `사망`만 가능
- 서명자 FK 선택 UI 없음
- 종료 계약 행: 재활성화 버튼 없음, “새 계약” 흐름
- 전환: preview → 영향목록·multiset·제안 종료일 → 명시 확인 checkbox → apply
- 확인 전 apply disabled; stale 시 preview·확인 폐기 안내
- 부분 성공처럼 보이는 중간 상태 금지

### 3.1 OpenAPI operation binding (R8-02 fail-closed)

W1D 라우터는 W1B/W1C `ERROR_RESPONSES` 와 동일 바인딩을 **operation마다 필수**로 한다.
상태 코드 문자열이 `str(spec)` 어딘가에 존재한다고 통과시키지 않는다.

| method path | success | response $ref ends with | request $ref ends with |
|---|---|---|---|
| GET `/api/v1/recipients/{id}/contracts` | **200** only | `/ContractListResponse` | (none) |
| GET `/api/v1/recipients/{id}/contracts/{cid}` | **200** only | `/ContractResponse` | (none) |
| POST `/api/v1/recipients/{id}/contracts` | **201** only | `/ContractResponse` | `/ContractCreateRequest` |
| POST `.../contracts/{cid}/end` | **200** only | `/ContractResponse` | `/ContractEndRequest` |
| POST `.../certification-transitions/preview` | **200** only | `/CertificationTransitionPreviewResponse` | `/CertificationTransitionPreviewRequest` |
| POST `.../certification-transitions/apply` | **200** only | `/CertificationTransitionApplyResponse` | `/CertificationTransitionApplyRequest` |

Every one of the six operations **must** declare error statuses
`401, 403, 404, 409, 422, 500`, each with
`application/json` schema `$ref` ending exactly in `/RecipientErrorEnvelope`.
Alternate success status (e.g. create with 200, get with 201) is forbidden.
Error-status presence is **not** product-owned optional documentation; RED treats
missing binding as `W1D_OPENAPI_*` product failure.

OpenAPI 생성 TypeScript는 승인 generator만 사용; 수동 편집 금지.

### 3.2 Free-text / null / empty exact rule (R8-10)

`end_reason_text`, `signer_name`, `signer_relationship_text`, `signer_phone` are
free text with **no enum, no DB default, no automatic `사망`**.

| request shape | persisted value |
|---|---|
| key omitted on create | `NULL` |
| explicit JSON `null` | `NULL` |
| explicit `""` (empty string) | `""` (empty string; **not** normalized to NULL) |
| non-empty Unicode | exact Unicode bytes/code points as sent |

End API: same table for `end_reason_text`. Initial UI value may be empty string;
server does not substitute defaults.

### 3.3 Reverse-period field_errors (R10-04)

Contract create/update period with `start_date > end_date` (when end_date is
non-null) is exact HTTP `422` + top-level envelope code `VALIDATION_ERROR`.

`field_errors` is exact **one-item** JSON equality with W1B/W1C
`_domain_error("VALIDATION_ERROR", field="end_date")`:

```json
[{"field": "end_date", "message": "입력값을 확인하세요."}]
```

- list length exactly **1**
- keys on the single object exactly `{field, message}` (no extras)
- message is the exact Korean string above (no arbitrary non-empty substitute)
- no duplicates, no `start_date`-only shape, no unrelated fields
- full ledger write-zero around the call
- empty `field_errors: []` is **not** acceptance

## 4. matrix ID → 검증 매핑

| Matrix ID | DB/PG | API | OA | UI unit | E2E | Marker prefix |
|---|---|---|---|---|---|---|
| W1-REC-03 | first-contract 경쟁·rollback·재계약 불변 | create 시 번호 발급 | response nullable | 미부여 표시 유지 | real PG E2E 발급 | `W1D_REC03_*` |
| W1-SIG-01 | 빈/부분 snapshot; guardian/payer 변경 후 불변 | 빈 signer 201 | 금지 FK/생년월일/주소 부재 | FK 강제 없음 | snapshot round trip | `W1D_SIG01_*` |
| W1-CON-01 | nullable round trip | 최소 201 | `contract_no` property 부재 | 시작일만 required | 최소 계약 E2E | `W1D_CON01_*` |
| W1-CON-02 | enum/default/backfill 부재; null·Unicode | free text 성공 | fixed enum 부재 | 초기 end_reason 빈 값 | `사망` 자동입력 0 | `W1D_CON02_*` |
| W1-CON-03 | reactivation trigger 거부 | 409 `CONTRACT_REACTIVATION_FORBIDDEN` | reactivate op 부재 | 재활성 버튼 0 | 새 계약 성공 | `W1D_CON03_*` |
| W1-CON-04 | same-service/cross-group/same-group matrix | 409 두 코드 | 409 문서화 | 충돌 표시 | 경계 matrix E2E | `W1D_CON04_*` |
| W1-TRN-01 | preview write 0 / hash | preview 200; 미확인 422 | preview/apply named schemas | apply disabled | 취소 시 불변 | `W1D_TRN01_*` |
| W1-TRN-02 | multiset mismatch 변경 0 | 422 `..._REPLACEMENT_MISMATCH` | replacement fields | 누락 시 차단 | 0/부분/중복 불변 | `W1D_TRN02_*` |
| W1-TRN-03 | stale 대상 4종; 동시 apply 1 | 409 STALE | stale code | preview 폐기 UI | concurrent apply | `W1D_TRN03_*` |
| W1-TRN-04 | fault 단계별 rollback; 감사 1건 | 부분성공 0 | apply response + correlation | 성공 재조회 | 4단계+감사 E2E | `W1D_TRN04_*` |
| W1-ABS-08 | `contract_no` 컬럼/property 0 | — | property 0 | 입력 0 | — | `W1D_ABS08_*` (PASS 분리) |
| W1-ABS-09 | end_reason enum/default/`discharge_date` 0 | — | 0 | 초기 value 빈 값 | — | `W1D_ABS09_*` (PASS 분리) |
| W1-ABS-10 | `service_start_date` NOT NULL 금지 | 누락 차단 0 | required 아님 | required 표시 0 | — | `W1D_ABS10_*` (PASS 분리) |

## 5. RED 구조와 파일 소유권 (Phase 1)

허용 write:

```text
review/plans/W1D_CONTRACT_TRANSITION_PLAN.md
review/evidence/w1d/RED.md
backend/tests/test_w1d_contract.py
backend/tests/test_w1d_postgres.py
frontend/src/test/W1DContractTransition.test.tsx
frontend/e2e/w1d-contract-transition.spec.ts
scripts/test-w1d-postgres.ps1
```

- product failure marker: `W1D_*_MISSING` / `W1D_*_FORBIDDEN` / domain code assert
- harness/environment failure marker: `W1D_HARNESS_*`
- ABS PASS는 제품 GREEN으로 주장하지 않음
- stage·commit·push·rebase·stash·환경 의존성 변경 없음

### 5.1 R11 write-zero / read ACL / E2E transition fixture (Joseph R4)

**H01 — rejected apply write-zero (full ledger + complete audit):**

Every rejected apply (unconfirmed confirmation, replacement MISMATCH matrix,
and every STALE dimension: grade, cert-date, grade-code, contract-period,
service-multiset) captures immediately **after intentional setup mutation**
and **before** the rejected call:

1. `_full_ledger_fingerprint(recipient_id)`
2. complete `_all_audit_rows()` canonical JSON

After rollback both must equal exactly. Count-only or selected-table
substitutes are forbidden. Snapshots must **not** be taken before an
intentional stale-setup mutation (would falsely fail).

**H02 — GET list/item ACL and purity:**

| request | expect |
|---|---|
| unauthenticated list/item | 401 `AUTHENTICATION_REQUIRED` + write-zero |
| authenticated no VIEW/MANAGE | 403 `PERMISSION_REQUIRED` + write-zero |
| `RECIPIENT_VIEW` list/item **without CSRF** | 200 + response equals persisted row + write-zero |
| VIEW missing recipient list/item | 404 `RECIPIENT_NOT_FOUND` + write-zero |
| VIEW missing contract item | 404 `CONTRACT_NOT_FOUND` + write-zero |

Executable: `test_w1d_pg_15_list_get_read_acl_and_purity`. ADMIN field/row
equality remains in `pg_12`.

**H03 / R12 — transition-stale E2E fixture (3 viewports):**

Before Playwright, for each of
`chromium-1440x1000|900|1366x768` × scenario `transition-stale`:

- W1C baseline tables must exist (else harness failure, not product-absent);
- canonical identity `^L[0-9]{10}$` only (local assert before API);
- one W1C identity + cert period + grade via public W1C APIs;
- two contracts via public W1D **contract-create** API (`HOME_CARE` then
  `HOME_BATH`) so first-contract issues immutable `recipient_no`;
- ContractResponse exact key set (R13-02):
  `id,recipient_id,service_type_code,service_group_code,start_date,end_date,
  service_start_date,signer_name,signer_relationship_text,signer_phone,
  end_reason_text,invalidated_at_utc,replacement_contract_id,row_version`
  with `service_group_code=LONG_TERM_CARE`, null invalidation/replacement/signer/
  end_reason/service_start/end, positive `row_version`;
- `recipient_no` must match `^[0-9]{6,}$` after first and second create and final
  persist (never printed);
- independent recipient per viewport; years 2030/2031/2032;
- full PostgreSQL equality verify (not count-only) before Playwright;
- marker (non-PII): `W1D_E2E_TRANSITION_FIXTURE … service_multiset=HOME_BATH,HOME_CARE`
  plus separate `W1D_E2E_TRANSITION_RECIPIENT_NO_ISSUED … issued=1`;
- product-present success requires 3 unique recipient IDs + 3 markers;
- W1D table absent → `W1D_E2E_SEED_TRANSITION_STALE_PRODUCT_ABSENT` (product RED);
- W1D present but API/body/invariant wrong → controlled
  `W1D_E2E_TRANSITION_PRODUCT_*` product RED (not harness), W1B baselines continue;
- transport/DB connectivity after proven cluster remains harness.

**E2E transition controls (R12-03, both pages required visible):**

```text
transition-new-start-date
transition-new-end-date
transition-new-grade-code
transition-new-grade-start-date
transition-new-grade-end-date
```

No silent skip. Preview POST 200 with exact two affected IDs, multiset
`HOME_BATH,HOME_CARE`, replacement_preview×2, matching `canonical_hash` A/B,
then apply 200 + STALE 409 as before.

**GET list VIEW (R12-04 / R13-03):** top-level key set must be exactly
`{"items"}` (no extra keys). Exact full-response JSON equality vs DB rows ordered
by `id ASC` for the recipient. Missing-recipient write-zero uses the **requested
missing recipient id** fingerprint/audit pair.

**R14-01 — exact per-ID response↔PostgreSQL equality (product-present fixture):**

When `erp.recipient_contract` is present and two public creates succeed:

- retain a normalized exact ContractResponse object keyed by each positive
  response contract ID (`created_by_id[cid]`);
- query exactly those two persisted IDs for the same recipient
  (`WHERE recipient_id = :rid AND id IN (:id0, :id1)`);
- require exact ID set/cardinality (2) and aggregate service multiset
  `HOME_BATH,HOME_CARE` (kept; not a substitute for per-ID equality);
- normalize each persisted row to the same 14-field ContractResponse set;
- for each ID, require full JSON/object equality between API response and
  persisted row: `id`, `recipient_id`, `service_type_code`,
  `service_group_code`, all three dates, three signer fields,
  `end_reason_text`, `invalidated_at_utc`, `replacement_contract_id`,
  exact `row_version`;
- no multiset-only or separately-positive substitute;
- all recipient_no format/immutability checks retained;
- checked conversion/normalization: malformed product fields emit controlled
  non-PII `W1D_E2E_TRANSITION_PRODUCT_*` markers (not uncaught harness exceptions).

**R14-02 — product schema exception vs infrastructure classification:**

After the W1D table is confirmed present:

- missing/wrong W1D columns, SQL programming/data/cardinality errors, or
  response/DB row-shape errors → product RED (`W1D_E2E_TRANSITION_PRODUCT_*`,
  exception class name only — never SQL text/message/PII);
- genuine transport/connection/cluster-enumeration failure remains harness
  (`OperationalError` or SQLSTATE `08*`);
- W1C identity/cert/grade baseline failures remain harness.

**R14-03 — embedded seed static AST gate:**

Before any exclusive live, extract `$SeedScript` here-string by locating the
line containing `$SeedScript = @"` and the later line whose trimmed content is
`"@`, then `ast.parse` / `compile` the intervening text with the backend
venv Python. Gate must report explicit success and must be re-run after any
wrapper edit. Do not rely only on PowerShell AST.

### R16 — Joseph R5 executable-RED closure (static-only; no new live)

| Finding | Executable location | Behavior |
|---|---|---|
| **J-W1D-R5-H01** W1C 2xx malform | `scripts/test-w1d-postgres.ps1` embedded seed: identity / certification-period / grade-period after nominal 200/201 | Transport + non-2xx remain harness. Malformed JSON/object/required types/values emit `W1D_E2E_TRANSITION_PRODUCT_W1C_*`, set `product_seed_red`, stop that viewport fixture; seed still completes for W1B baselines (`SEED_OK`). Never generic `W1D_HARNESS_E2E_SEED_FAILED` for malformed 2xx setup. |
| **J-W1D-R5-H02** strict ContractResponse | seed `strict_api_contract_response` vs `normalize_db_contract_row` | API: `type(value) is int` (not bool) for ids/row_version; exact `YYYY-MM-DD` strings; exact null for active create nullables; exact 14-key set. No `int()`/`str()[:10]` coercion on API. DB driver dates/ints normalized separately fail-closed. Per-ID full JSON equality retained. |
| **J-W1D-R5-H03** SQLSTATE 08* | seed product-verify `except` | For every `DBAPIError`, extract `orig.sqlstate`/`pgcode`; `08*` → harness **before** ProgrammingError/DataError/IntegrityError product branches. `OperationalError` harness. Class name only. |
| **J-W1D-R5-H04** concurrent loser write-zero | `test_w1d_postgres.py` `pg_08`: `_full_ledger_state` + `_assert_single_winner_ledger_projection` | See **R17** exact full-row projection (supersedes R16 non-decreasing wording). |
| **J-W1D-R5-M01** recipient_no format | `pg_00` `_assert_recipient_no_exact` | Exact `^[0-9]{6,}$` on first issuance, second recipient, re-contract/final persisted value (plus inequality/immutability). |

### R17 — exact single-winner full-row projection (REGINA-W1D-R16-H01)

R16 claimed loser-only writes fail but `assert_ended_only` accepted any
`row_version >= before` and new rows used selected-field checks. **R17 seals:**

**Ended old cert / grade / contract (winner path only):**

- after keyset **equals** before keyset (complete to_jsonb columns);
- `row_version` is strict non-bool `int` and **exactly** `before + 1`
  (rejects unchanged and `+2`/double-write);
- `end_date` exactly `proposed_end` (= `new_start - 1 day`);
- generated period column (`certification_period` / `grade_period` /
  `contract_period`) recomputed half-open `[start, end+1)`;
- **named metadata deltas:** `updated_by_account_id` = confirmer account id;
  `updated_at_utc` non-null tz-aware and `>=` pre-race value;
- optional contract `end_reason_text` only when sealed replacement requires it;
- every other column exact-equal to pre-race (including
  `invalidated_at_utc`, replacement FKs, created_*, start_date, service FKs,
  signers on old contract).

**Winner-created cert / grade / contract:**

- complete expected keysets for W1C `0010` cert/grade tables and planned W1D
  `0011` `recipient_contract` (see §2.6 + actor columns);
- every column validated from sealed inputs/IDs (winner response IDs, recipient,
  service_type catalog id, dates, grade_code, null invalidation/replacement,
  actor ids, `row_version == 1`, signer/service/end_reason from sealed
  replacement request) — **never** by copying unchecked after-state values;
- no unconsumed key/value.

**Unchanged / audit:** recipient, identity, counter exact; audit prefix exact +
exactly one `CERTIFICATION_TRANSITION_APPLY` with full audit keyset and
projection object keys. Dual lock observation, one `ok`, one exact STALE
unchanged.

**Single-winner projection contract:** loser STALE contributes zero ledger rows
and zero audit events. Any unexplained row/column/audit/counter mutation is
`W1D_TRN03_*` fail-closed. Hash-only or selected-count comparisons are not
sufficient.

### R18 — Joseph R6 H01 / H04 / M01 (static-only reseal)

Joseph R6 closed H02/H03; confirmed P1 blockers H01, H04, M01. Benefit/approval/
guardian/payer remain **out of** transition target ledger scope (canonical 04 /
plan §2.8).

| Finding | Executable | Exact contract |
|---|---|---|
| **H01** W1C 2xx exact | seed `validate_w1c_identity_2xx` / `validate_w1c_cert_2xx` / `validate_w1c_grade_2xx` + `r18_w1c_mutant_selfcheck` | Exact top-level keysets only (identity 3 keys; cert 7 keys; grade 9 keys). Strict non-bool ints, exact dates/strings/nulls, create `row_version==1`. Missing/extra/wrong type/bool/value → `W1D_E2E_TRANSITION_PRODUCT_W1C_*`. Transport/non-2xx harness. Mutants map each form to a named fail branch. |
| **M01** recipient_no | `_assert_recipient_no_exact` + `_r18_recipient_no_mutant_selfcheck`; seed raw `type is str` | `type(value) is str` and `^[0-9]{6,}$` on the raw value — no `str()`/`strip()`. Mutants reject whitespace, int, bool, short, signs/decimal. |
| **H04** winner | `_pack_structured_winner_result` / `_assert_structured_winner_shape` | Structured dict only: `status`, `new_certification_period_id`, `new_grade_period_id`, `new_contract_ids` (list of one strict positive int), `audit_correlation_id` (UUID). **No** `ok:` text, `literal_eval`, `int()`, or digit-regex fallback. |
| **H04** timestamp | one sealed apply `changed_at` | Product must capture **one** apply timestamp after recipient lock and use it for: old cert/grade/contract `updated_at_utc`; every new cert/grade/contract `created_at_utc`+`updated_at_utc`; audit `occurred_at_utc`. RED requires exact equality across those values, strict UTC normalize, each old pre-race `updated_at` **strictly less**, and inclusion in `clock_timestamp` window from immediately before blocker release through after workers join. Merely nondecreasing is **not** enough. |
| **H04** open range | `_assert_open_ended_range_exact` | Exact normalized `[new_start,)` for NULL `end_date` half-open unbounded upper. Reject infinity-containing / prefix-only garbage. |
| **H04** audit JSON | pre-race `_capture_authorized_preview` A==B; `_canonical_transition_projection` before (`include_new_ids=False`) and after (`True` + winner IDs) | Appended `before_json`/`after_json` exact object equality to those projections; same authorized `preview_hash`; before omits `new_ids`; after has exact new id map + multiset/periods. |

### R19 — pure shared validators + real mutant selfchecks (Regina R18 REQUIRED_CHANGES)

R18 defect: `_r18_winner_mutant_selfcheck` caught `Exception`, but `_fail` raises
`pytest.outcomes.Failed` (`BaseException`), aborting `pg_08` on the first
expected-rejected mutant. **Do not** catch `BaseException`/`Failed`.

| Area | Pure function (returns error code / None) | Assertion | Mutant selfcheck |
|---|---|---|---|
| Winner shape | `_validate_structured_winner_shape` | `_assert_structured_winner_shape` → `_fail` only after error | `_r19_winner_mutant_selfcheck` calls pure validator only |
| Pack | `_pack_structured_winner_result` enforces same types; product UUID/str → **worker `UUID` object** | worker stores packed dict | covered by pure shape check |
| Timestamp | `_validate_ts_exact_equal`, `_validate_ts_strictly_after`, `_validate_ts_in_window`, `_validate_old_row_sealed_timestamp`, `_try_normalize_utc_timestamp` | old/new/audit/window use same predicates | `_r19_timestamp_mutant_selfcheck` |
| Open range | exact `[start,)` normalize | `_assert_open_ended_range_exact` | `_r19_open_range_mutant_selfcheck` |
| Audit JSON | `_validate_exact_audit_projection` | single-winner append before/after | `_r19_audit_proj_mutant_selfcheck` exercises same predicate |

Worker dict keys exact: `status`, `new_certification_period_id`,
`new_grade_period_id`, `new_contract_ids`, `audit_correlation_id`. Internal
`audit_correlation_id` type is **`UUID` only** (no str acceptance in structure).

### R20 — pack UUID boundary + shared normalizer + full audit mutants

Regina R19 REQUIRED_CHANGES:

1. **Service→worker pack:** `_try_pack_structured_winner_result` /
   `_pack_structured_winner_result` accept `type(corr) is UUID` **only**.
   UUID-looking `str` is rejected (no parse/coercion). HTTP wire may serialize
   UUID as JSON string; the direct Python/Pydantic service field and worker
   structure are UUID objects. Pack mutant selfcheck
   `_r20_pack_mutant_selfcheck` included in aggregate.
2. **One shared timestamp normalizer:** `_normalize_utc_timestamp` **must**
   call `_try_normalize_utc_timestamp` and map error codes to existing
   `W1D_HARNESS_TIMESTAMP_*` markers. Coupling guard
   `_r20_normalizer_coupling_selfcheck` (source + call counter) fails if
   decoupled. Direct probe reports `ACTUAL_NORMALIZER_USES_PURE=True`.
3. **Audit mutants:** `_r19_audit_proj_mutant_selfcheck` exercises
   `_validate_exact_audit_projection` for missing/wrong/extra `new_ids`
   members, nested value/key/container faults, preview hash, top-level
   missing/extra — same predicate as the live append assertion.

### R21 — HTTP apply correlation chain + JSON-domain audit + E2E strict IDs

Joseph R7 REQUIRED_CHANGES (P1 package): HTTP wire vs audit/request_id evidence,
JSON-domain audit predicate, plan/RED wording, E2E Number coercion.

| Item | Executable |
|---|---|
| Internal worker UUID object | R20 pack unchanged: `type(corr) is UUID` only |
| HTTP apply | `test_w1d_pg_16_http_apply_success_correlation_audit`: real TestClient preview+apply 200; `_validate_http_apply_success_response` exact keyset + strict ints + canonical lowercase UUID string; **HTTP correlation == same-apply audit `request_id`** (single append, recipient-scoped) |
| Pure HTTP mutants | `_r21_http_apply_mutant_selfcheck` in aggregate: divergent UUID, uppercase, malformed, missing/extra keys, UUID object/int/bool/None corr, bad ID arrays |
| Audit JSON-domain | `_json_domain_values_equal` (no `default=str`); date/tuple mutants rejected |
| E2E apply IDs | `typeof === 'number'`, `Number.isInteger`, positive, unique; readback `id === cid` without `Number()` |

### R22 — R7 dual-report evidence + JSON-domain harden + full HTTP ID bind (static-only)

Regina AUDIT-028 REQUIRED_CHANGES after R21. **Mode: static-only.** Status remains
`RED_VALID_PENDING_DESIGN_AUDIT` (not approval, not product GREEN). No live
wrapper/DB campaign; R14 cleanup is historical only.

| Item | Executable |
|---|---|
| R7 evidence | RED lists **both** same-path report seals/verdicts/findings (f4db…/24839 HTTP P1 and current path 661528…/15229 audit non-JSON + plan/RED B2). Do not edit the report. |
| Cleanup wording | No R22 live cleanup/residual certification. R14 cleanup is historical only. R7 observed existing `backend/.pytest_cache`. Root `node_modules` and named generated artifact paths were absent only as **read-only observations**. No current runtime-zero claim. |
| JSON-domain | `_is_json_domain_value` rejects NaN/+inf/-inf, UUID/date/datetime, custom objects, tuple/set, non-string keys, nested non-JSON; finite floats may match when types/values exact. Shared-predicate mutants for custom/UUID/NaN/±inf/nonstr-key/nested-set plus date/tuple. |
| Audit request_id | `_canonical_audit_request_id`: UUID object via `str(uuid)` or already-canonical lowercase string only; never `.lower()` coerce. Uppercase/noncanonical/malformed fail. HTTP `audit_correlation_id` exact-equal. |
| HTTP ID bind | `_validate_http_apply_success_response` requires exact ended cert/grade/contract ID lists, exact new cert/grade/contract IDs, recipient_id, recipient_no, audit correlation — no optional/count-only. pg_16 retains seeded old IDs; binds `after_json.new_ids` fail-closed; proves new IDs differ from old and match row properties/cardinality. |
| Pure mutants | Aggregate includes R22 noncanonical expected audit ID, wrong ended/new ID lists, JSON-domain mutants. |
| Frozen | E2E, wrapper, contract test, Vitest — exact R21 seals. Allowlist: plan, RED, `test_w1d_postgres.py` only. |

### R24 — Joseph R8 active pg_05 audit + ContractResponse H02 (static-only)

Joseph R8 REQUIRED_CHANGES after R23. **Mode: static-only.** Status remains
`RED_VALID_PENDING_DESIGN_AUDIT` (not approval, not product GREEN). No live
wrapper/DB campaign; R14 cleanup historical only.

| Item | Executable |
|---|---|
| pg_05 audit | Active path routes before/after through `_validate_exact_audit_projection` (shared JSON-domain). No `int()` on audit `new_ids`; no `json.dumps(..., default=str)` projection compare. Exact authorized hash, structure, new-id types/order/values, canonical request_id, audit prefix + one append. |
| ContractResponse H02 | `_validate_contract_response_strict` 14-key/type/value/null gate before row match. API path has no int/date coercion. DB-side `_normalize_db_contract_row_for_api` only. Direct no-DB mutants: string IDs + date objects rejected; valid body passes. |
| Seed sync | Wrapper embedded seed keeps H01–H04/M01; API↔DB compare uses exact equality of already-normalized JSON primitives (no `default=str`). Opener/terminator extraction contract preserved. |
| Pure mutants | Aggregate includes `_r24_contract_response_mutant_selfcheck` + `_r24_pg05_audit_path_source_selfcheck`. |
| Frozen | contract test, Vitest, E2E exact. Allowlist: postgres RED, wrapper, plan, RED. |

### R25 — Ruff I001 pg_10 import-order evidence correction (static-only)

Regina R24 independent integration: `REGINA_W1D_R24_INTEGRATION_RESULT=REQUIRED_CHANGES_STATIC_I001`.
R24 writer claimed w1c-before-w1d fixed I001, but independent Ruff with
`.venv\Scripts\python.exe -B -m ruff check --no-cache --config pyproject.toml
tests/test_w1d_contract.py tests/test_w1d_postgres.py` returned **I001 exit 1**.

| Item | Correction |
|---|---|
| pg_10 import block | Exact Ruff order: first `from app.domains.w1d import fault as w1d_fault  # type: ignore`, blank line, then `app.domains.w1c.schemas` block + `W1CService`. Behavior unchanged. |
| Evidence | Plan/RED retract w1c-before-w1d “passed” claim; record actual R25 rerun exit 0. |
| Status | `RED_VALID_PENDING_DESIGN_AUDIT` static-only; not approval/GREEN/live/product/cleanup. |
| Frozen | wrapper, contract test, Vitest, E2E exact R24 seals. Allowlist: postgres, plan, RED only. |

## 6. 구현 단계 게이트 (Phase 1 이후, 미승인)

구현은 레지나 재봉인 후에만 시작한다. 예상 순서:

1. migration `20260730_0011_w1d_recipient_contract`
2. domain schemas/policies/service + API router
3. OpenAPI generator 재실행 (수동 TS 편집 금지)
4. frontend panel + w1dApi
5. GREEN 증거·독립 감사·Spark 회귀·Marco·Regina PASS

## 7. 명시적 금지 (재진술)

```text
contract_no / contract_sequence
signer_guardian_id / signer_payer_id / signer birth_date/address
end_reason_code enum/check/default/backfill
사망 기본값
discharge_date
service_start_date NOT NULL 또는 누락 차단
종료 계약 재활성화
preview write
확인 없는 apply
부분 transaction 성공
W1E·Wave 2 선구현
W1C migration·제품 계약 약화
생성 OpenAPI TypeScript 수동 편집
실 개인정보·운영 DB·운영 자격증명
```

## 8. Finding 폐쇄 맵 (Opus + Joseph R2/R3)

| ID | 계획 위치 | RED 위치 |
|---|---|---|
| B1–M3 / N2 | prior CLOSED | do not reopen |
| H3 | wrapper stage A | live W1C-head self-check PASS |
| **Joseph B01** cert stale valid mutation | §2.8 stale | pg_08 cert end extend + setup commit |
| **Joseph H01** virgin counter | §2.3 | pg_00 first; `before is None`; 1→2 second recipient |
| **Joseph H02** apply race | §2.8 | blocker FOR UPDATE + dual Lock wait; winner IDs |
| **Joseph H03** cross-group serialize | §2.6 parent FOR UPDATE | pg_09 submit-both-first; exact SQLSTATE |
| **Joseph H04** replacement matrix | §2.3 | pg_05 full MISMATCH matrix |
| **Joseph H05** 10 fault labels | §2.8 | pg_10 parameterized |
| **Joseph H06** live E2E | §3/UI | playwright no mocks; wrapper stage D |
| **Joseph M01–M09/L01** | plan+wrapper+tests | fingerprints, ACL, OpenAPI refs, stages, residual, WS |
| audit_correlation_id | §2.2 UUID=request_id | sealed |
| cert null transition | §2.2 `CERTIFICATION_IDENTITY_NOT_FOUND` | sealed |

## 9. Phase 1 완료 자기점검

- [x] N1/N2/N3 + token/fault/clock plan+RED 봉인 (`RED.md` R2 폐쇄표)
- [x] W1C-head harness self-check 실제 PASS
- [x] 의도 product RED marker 유지 (revision 부재)
- [x] ABS PASS 분리 (제품 GREEN 아님)
- [x] wrapper product vs harness 구분
- [x] R22–R25 static-only: no live cleanup/residual certification this round; R14 cleanup is historical only; R7 observed existing `backend/.pytest_cache`; root `node_modules` and named generated artifact paths were absent only as read-only observations (no current runtime-zero claim)
- [x] `git diff --check` + allowlist only + staged 0
- [x] 제품 구현 0, 판정 `RED_VALID_PENDING_DESIGN_AUDIT` (R25 static-only; not approval/GREEN)
- [x] Joseph R8: pg_05 shared exact-audit path + ContractResponse strict H02 gate (executable RED; product still absent)
- [x] R25: pg_10 fault import I001 — w1d-before-w1c (with blank line) as required by project Ruff; R24 w1c-before-w1d claim was false
