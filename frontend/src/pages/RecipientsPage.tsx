import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent, UIEvent } from 'react';
import RecipientW1cPanel from '../components/recipients/RecipientW1cPanel';
import RecipientContractPanel from '../components/recipients/RecipientContractPanel';
import RecipientServicePlanNoticePanel from '../components/recipients/RecipientServicePlanNoticePanel';
import {
  createRecipientBasicBatch,
  saveRecipientDetailBatch,
  updateRecipientBasicBatch,
  type BasicGuardianMutation,
  type RecipientDetailBatchRequest,
} from '../services/recipientDetailBatchApi';
import { listBenefitPeriods, normalizeApprovalAmountKrw } from '../services/w1cApi';
import '../styles/recipients.css';
import { ApiError } from '../services/api';
import {
  getRecipient,
  isRecipientStatus,
  listGuardians,
  listRecipients,
  updateRecipient,
} from '../services/recipientApi';
import type {
  Guardian,
  GuardianCreateRequest,
  Recipient,
  RecipientCreateRequest,
  RecipientListItem,
  RecipientListResponse,
  RecipientListServiceGroupItem,
  RecipientListStatusFilter,
  RecipientSexCode,
  RecipientStatus,
  RecipientUpdateRequest,
} from '../services/recipientApi';

type RecipientFormState = {
  name: string;
  birth_date: string;
  sex_code: RecipientSexCode | '';
  recipient_status: RecipientStatus;
  postal_code: string;
  address: string;
  mobile_phone: string;
  memo: string;
};

type CopayBenefitCode = 'GENERAL' | 'BASIC_LIVELIHOOD' | 'REDUCTION_6' | 'REDUCTION_9';

type CopayPeriodSnapshot = {
  id: number;
  benefit_code: string;
  start_text: string;
  invalidated_at_utc: string | null;
  row_version: number;
};

type PendingCopaySave = {
  code: CopayBenefitCode;
  startText: string;
};

function normalizeCopayBenefitCode(value: string | null | undefined): CopayBenefitCode {
  if (value === 'BASIC_LIVELIHOOD') return 'BASIC_LIVELIHOOD';
  if (value === 'REDUCTION_6' || value === 'MEDICAL_6') return 'REDUCTION_6';
  if (value === 'REDUCTION_9' || value === 'MEDICAL_9') return 'REDUCTION_9';
  return 'GENERAL';
}

function effectiveCopayPeriod(
  items: CopayPeriodSnapshot[],
): CopayPeriodSnapshot | null {
  return items.find((item) => !item.invalidated_at_utc) ?? null;
}

function buildCopayBenefitMutations(
  existing: CopayPeriodSnapshot | null,
  draft: PendingCopaySave,
): RecipientDetailBatchRequest['benefit_period'] | undefined {
  if (!existing) {
    return { payload: { benefit_code: draft.code, start_text: draft.startText } };
  }
  const existingCode = normalizeCopayBenefitCode(existing.benefit_code);
  if (existingCode === draft.code && existing.start_text === draft.startText) {
    return undefined;
  }
  return {
    period_id: existing.id,
    payload: {
      expected_row_version: existing.row_version,
      benefit_code: draft.code,
      start_text: draft.startText,
    },
  };
}

type RecipientEditableField =
  | 'name'
  | 'birth_date'
  | 'sex_code'
  | 'recipient_status'
  | 'postal_code'
  | 'address'
  | 'mobile_phone'
  | 'memo';

type RecipientFieldConflict = {
  field: RecipientEditableField;
  label: string;
  userValue: string;
  serverValue: string;
};

type RecipientStaleConflict = {
  original: Recipient;
  latest: Recipient;
  draftAtConflict: RecipientFormState;
  sameFieldConflicts: RecipientFieldConflict[];
  /** When false, same-field collision: no automatic reapply; form shows server latest. */
  canAutoReapply: boolean;
};

type GuardianFormState = {
  name: string;
  phone: string;
  email: string;
  address: string;
  relationship_text: string;
};

type GuardianSlot = 0 | 1;
type GuardianFormSlots = [GuardianFormState, GuardianFormState];
/** null=self, 0/1=two UI guardian slots, 'unlisted'=existing payer outside the two slots. */
type PayerGuardianSlot = null | GuardianSlot | 'unlisted';

type EmbeddedRecipient = Recipient & {
  guardians?: Guardian[];
};

const PAGE_SIZE = 100;

/** UI display order: 이용중, 전체, 계약종료, 대기중 */
const LIST_STATUS_FILTERS: readonly RecipientListStatusFilter[] = [
  'ACTIVE',
  'ALL',
  'ENDED',
  'WAITING',
];

const LIST_STATUS_LABELS: Record<RecipientListStatusFilter, string> = {
  ACTIVE: '이용중',
  ALL: '전체',
  ENDED: '계약종료',
  WAITING: '대기중',
};

function parseStatusFilter(rawValue: string | null): RecipientListStatusFilter {
  if (rawValue && (LIST_STATUS_FILTERS as readonly string[]).includes(rawValue)) {
    return rawValue as RecipientListStatusFilter;
  }
  // First screen / missing URL status defaults to ACTIVE (UI). API default remains ALL when omitted.
  return 'ACTIVE';
}

/**
 * Read-only list projection for summary display (name/grade context only).
 * Never use this as an editable detail form source or PATCH payload base:
 * list rows do not carry recipient_status; inventing ACTIVE would overwrite real tags.
 */
function recipientIdentityFromListItem(item: RecipientListItem): Recipient {
  return {
    id: item.id,
    name: item.name,
    birth_date: item.birth_date,
    sex_code: item.sex_code,
    // Placeholder only for TypeScript Recipient shape; not used for edit/PATCH.
    recipient_status: 'ACTIVE',
    recipient_no: item.recipient_no,
    postal_code: item.postal_code,
    address: item.address,
    mobile_phone: item.mobile_phone,
    memo: item.memo,
    // List projection has no payer field; never invent from names/snapshots.
    payer_guardian_id: null,
    row_version: item.row_version,
  };
}

/** Patch list-row identity fields after detail save; keep server projection columns. */
function mergeRecipientIntoListItem(
  item: RecipientListItem,
  recipient: Recipient,
): RecipientListItem {
  return {
    ...item,
    id: recipient.id,
    name: recipient.name,
    birth_date: recipient.birth_date,
    sex_code: recipient.sex_code,
    recipient_no: recipient.recipient_no,
    postal_code: recipient.postal_code,
    address: recipient.address,
    mobile_phone: recipient.mobile_phone,
    memo: recipient.memo,
    row_version: recipient.row_version,
  };
}

function formatGradeCode(value: string | null | undefined): string {
  if (value == null || !String(value).trim()) return '미지정';
  const normalized = String(value).trim();
  return /등급$/.test(normalized) ? normalized : `${normalized}등급`;
}

function formatBenefitCode(value: string | null | undefined): string {
  if (value == null || !String(value).trim()) return '없음';
  return String(value).trim();
}

function formatCopaymentRate(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '미지정';
  // 15% is the standard general copay rate; list projection maps it to the same label as GENERAL.
  if (value === 15) return '일반';
  return `${value}%`;
}

function formatListServices(services: RecipientListServiceGroupItem[] | null | undefined): string {
  if (!services?.length) return '없음';
  return services
    .map((group) => {
      const types = group.service_types?.length
        ? group.service_types.map((type) => type.display_name).join(', ')
        : '없음';
      return `${group.display_name}: ${types}`;
    })
    .join(' · ');
}

const emptyRecipientForm = (): RecipientFormState => ({
  name: '',
  birth_date: '',
  sex_code: '',
  recipient_status: 'ACTIVE',
  postal_code: '',
  address: '',
  mobile_phone: '',
  memo: '',
});

const emptyGuardianForm = (): GuardianFormState => ({
  name: '',
  phone: '',
  email: '',
  address: '',
  relationship_text: '',
});

const guardianSlotsFromGuardians = (
  guardians: Guardian[],
): [Guardian | undefined, Guardian | undefined] => {
  const slots: [Guardian | undefined, Guardian | undefined] = [undefined, undefined];
  for (const guardian of guardians) {
    const slotIndex = guardian.slot_no === 1 ? 0 : guardian.slot_no === 2 ? 1 : slots[0] ? 1 : 0;
    if (!slots[slotIndex]) slots[slotIndex] = guardian;
  }
  return slots;
};

const guardianFormsFromGuardians = (guardians: Guardian[]): GuardianFormSlots => {
  const slots = guardianSlotsFromGuardians(guardians);
  return [
    slots[0] ? guardianFormFromGuardian(slots[0]) : emptyGuardianForm(),
    slots[1] ? guardianFormFromGuardian(slots[1]) : emptyGuardianForm(),
  ];
};

function payerSlotFromRecipient(
  recipient: Recipient | null | undefined,
  guardianIds: [string | null, string | null],
): PayerGuardianSlot {
  const payerId = recipient?.payer_guardian_id;
  if (payerId == null) return null;
  const normalized = normalizeId(payerId);
  if (guardianIds[0] && guardianIds[0] === normalized) return 0;
  if (guardianIds[1] && guardianIds[1] === normalized) return 1;
  // Preserve an existing payer that is outside the two editable UI slots.
  return 'unlisted';
}

function optionalText(value: string): string | null {
  const normalized = value.trim();
  return normalized || null;
}

function formatMobilePhoneInput(value: string): string {
  const digits = value.replace(/\D/g, '');
  const localDigits = (digits.startsWith('010') ? digits.slice(3) : digits).slice(0, 8);
  if (!localDigits) return '010-';
  if (localDigits.length <= 4) return `010-${localDigits}`;
  return `010-${localDigits.slice(0, 4)}-${localDigits.slice(4)}`;
}

function recipientCreatePayload(form: RecipientFormState): RecipientCreateRequest {
  return {
    name: optionalText(form.name),
    birth_date: form.birth_date || null,
    sex_code: form.sex_code || null,
    postal_code: optionalText(form.postal_code),
    address: optionalText(form.address),
    mobile_phone: form.mobile_phone.trim(),
    memo: optionalText(form.memo),
  };
}

const RECIPIENT_FIELD_LABELS: Record<RecipientEditableField, string> = {
  name: '이름',
  birth_date: '생년월일',
  sex_code: '성별',
  recipient_status: '상태',
  postal_code: '우편번호',
  address: '주소',
  mobile_phone: '휴대전화',
  memo: '출처 메모',
};

function formatFieldDisplay(value: string | null | undefined): string {
  if (value == null || value === '') return '없음';
  return value;
}

/**
 * Shared normalization for draft vs baseline dirty comparison and PATCH diffs.
 * Trim text, empty/whitespace-only optional fields → null (same as form payload).
 */
function recipientComparableValues(recipient: Recipient): Record<RecipientEditableField, string | null> {
  return {
    name: optionalText(recipient.name ?? ''),
    birth_date: recipient.birth_date,
    sex_code: recipient.sex_code,
    recipient_status: recipient.recipient_status,
    postal_code: optionalText(recipient.postal_code ?? ''),
    address: optionalText(recipient.address ?? ''),
    mobile_phone: recipient.mobile_phone.trim(),
    memo: optionalText(recipient.memo ?? ''),
  };
}

function formComparableValues(form: RecipientFormState): Record<RecipientEditableField, string | null> {
  return {
    name: optionalText(form.name),
    birth_date: form.birth_date || null,
    sex_code: form.sex_code || null,
    recipient_status: form.recipient_status,
    postal_code: optionalText(form.postal_code),
    address: optionalText(form.address),
    mobile_phone: form.mobile_phone.trim(),
    memo: optionalText(form.memo),
  };
}

function changedRecipientFields(
  baseline: Recipient,
  draft: RecipientFormState,
): RecipientEditableField[] {
  const base = recipientComparableValues(baseline);
  const next = formComparableValues(draft);
  return (Object.keys(base) as RecipientEditableField[]).filter((key) => base[key] !== next[key]);
}

function serverChangedRecipientFields(original: Recipient, latest: Recipient): RecipientEditableField[] {
  const a = recipientComparableValues(original);
  const b = recipientComparableValues(latest);
  return (Object.keys(a) as RecipientEditableField[]).filter((key) => a[key] !== b[key]);
}

/** PATCH body with only fields that differ from baseline (omit untouched, e.g. status). */
function recipientChangedFieldsPayload(
  baseline: Recipient,
  draft: RecipientFormState,
  expectedRowVersion: number,
): RecipientUpdateRequest {
  const payload: RecipientUpdateRequest = { expected_row_version: expectedRowVersion };
  const changed = changedRecipientFields(baseline, draft);
  const next = formComparableValues(draft);
  for (const field of changed) {
    if (field === 'name') payload.name = next.name;
    else if (field === 'birth_date') payload.birth_date = next.birth_date;
    else if (field === 'sex_code') payload.sex_code = next.sex_code as RecipientSexCode | null;
    else if (field === 'recipient_status') {
      payload.recipient_status = next.recipient_status as RecipientStatus;
    } else if (field === 'postal_code') payload.postal_code = next.postal_code;
    else if (field === 'address') payload.address = next.address;
    else if (field === 'mobile_phone') payload.mobile_phone = next.mobile_phone ?? undefined;
    else if (field === 'memo') payload.memo = next.memo;
  }
  return payload;
}

function recipientHasDraftChanges(baseline: Recipient, draft: RecipientFormState): boolean {
  return changedRecipientFields(baseline, draft).length > 0;
}

/**
 * Runtime-validate detail GET before opening the editor.
 * Rejects wrong id, missing/null/invalid recipient_status, or missing required mobile phone.
 */
function validateDetailRecipient(raw: unknown, expectedId: string): Recipient | null {
  if (raw === null || typeof raw !== 'object') return null;
  const candidate = raw as Partial<Recipient>;
  if (normalizeId(candidate.id) !== expectedId) return null;
  if (!isRecipientStatus(candidate.recipient_status)) return null;
  if (typeof candidate.row_version !== 'number' || !(candidate.row_version > 0)) return null;
  if (candidate.name !== null && typeof candidate.name !== 'string') return null;
  if (candidate.birth_date !== null && typeof candidate.birth_date !== 'string') return null;
  if (
    candidate.sex_code !== null &&
    candidate.sex_code !== 'MALE' &&
    candidate.sex_code !== 'FEMALE'
  ) return null;
  if (typeof candidate.mobile_phone !== 'string' || !candidate.mobile_phone.trim()) return null;
  // payer_guardian_id: null = self; positive number = guardian; missing treated as null for older mocks.
  if (
    candidate.payer_guardian_id !== undefined &&
    candidate.payer_guardian_id !== null &&
    (typeof candidate.payer_guardian_id !== 'number' || !(candidate.payer_guardian_id > 0))
  ) {
    return null;
  }
  return {
    ...(candidate as Recipient),
    payer_guardian_id:
      candidate.payer_guardian_id === undefined ? null : candidate.payer_guardian_id,
  };
}

function recipientFormFromRecipient(recipient: Recipient): RecipientFormState {
  return {
    name: recipient.name ?? '',
    birth_date: recipient.birth_date ?? '',
    sex_code: recipient.sex_code ?? '',
    recipient_status: recipient.recipient_status,
    postal_code: recipient.postal_code ?? '',
    address: recipient.address ?? '',
    mobile_phone: recipient.mobile_phone,
    memo: recipient.memo ?? '',
  };
}

/**
 * Merge user-changed fields from draft onto latest server values.
 * When excludeFields is set (same-field conflicts), those fields stay at server latest;
 * only disjoint user edits are preserved.
 */
function mergeUserChangesOntoLatest(
  latest: Recipient,
  original: Recipient,
  draft: RecipientFormState,
  excludeFields?: ReadonlySet<RecipientEditableField>,
): RecipientFormState {
  const merged = recipientFormFromRecipient(latest);
  const userChanged = changedRecipientFields(original, draft);
  const draftValues = formComparableValues(draft);
  for (const field of userChanged) {
    if (excludeFields?.has(field)) continue;
    if (field === 'name') merged.name = draftValues.name ?? '';
    else if (field === 'birth_date') merged.birth_date = draftValues.birth_date ?? '';
    else if (field === 'sex_code') merged.sex_code = (draftValues.sex_code as RecipientSexCode | null) ?? '';
    else if (field === 'recipient_status') {
      merged.recipient_status = (draftValues.recipient_status as RecipientStatus) ?? 'ACTIVE';
    } else if (field === 'postal_code') merged.postal_code = draftValues.postal_code ?? '';
    else if (field === 'address') merged.address = draftValues.address ?? '';
    else if (field === 'mobile_phone') merged.mobile_phone = draftValues.mobile_phone ?? '';
    else if (field === 'memo') merged.memo = draftValues.memo ?? '';
  }
  return merged;
}

function guardianFormFromGuardian(guardian: Guardian): GuardianFormState {
  return {
    name: guardian.name ?? '',
    phone: guardian.phone ?? '',
    email: guardian.email ?? '',
    address: guardian.address ?? '',
    relationship_text: guardian.relationship_text ?? '',
  };
}

function guardianPayload(form: GuardianFormState): GuardianCreateRequest {
  return {
    name: optionalText(form.name),
    phone: optionalText(form.phone),
    email: optionalText(form.email),
    address: optionalText(form.address),
    relationship_text: optionalText(form.relationship_text),
  };
}

function guardianSlotHasContent(form: GuardianFormState): boolean {
  return Boolean(
    form.name.trim() ||
      form.phone.trim() ||
      form.email.trim() ||
      form.address.trim() ||
      form.relationship_text.trim(),
  );
}

function guardianFormsEqual(a: GuardianFormState, b: GuardianFormState): boolean {
  return (
    a.name.trim() === b.name.trim() &&
    a.phone.trim() === b.phone.trim() &&
    a.email.trim() === b.email.trim() &&
    a.address.trim() === b.address.trim() &&
    a.relationship_text.trim() === b.relationship_text.trim()
  );
}

function valueFromResult<T>(result: PromiseSettledResult<T>): T | undefined {
  return result.status === 'fulfilled' ? result.value : undefined;
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    'name' in error &&
    (error as { name?: unknown }).name === 'AbortError'
  );
}

function isApiErrorCode(error: unknown, code: string): boolean {
  const isKnownApiError =
    error instanceof ApiError ||
    (error instanceof Error && error.name === 'ApiError');
  return isKnownApiError && (error as { code?: string }).code === code;
}

/** Validate list response contract fields used for infinite scroll. */
function isValidListResponse(response: RecipientListResponse): boolean {
  if (!response || typeof response !== 'object') return false;
  if (!Array.isArray(response.items)) return false;
  if (typeof response.total !== 'number' || !Number.isFinite(response.total) || response.total < 0) {
    return false;
  }
  if (typeof response.page !== 'number' || !Number.isFinite(response.page) || response.page < 1) {
    return false;
  }
  if (
    typeof response.page_size !== 'number' ||
    !Number.isFinite(response.page_size) ||
    response.page_size < 1
  ) {
    return false;
  }
  return true;
}

/** Append incoming rows, dropping duplicates by recipient id. */
function appendItemsById(
  existing: RecipientListItem[],
  incoming: RecipientListItem[],
): RecipientListItem[] {
  const seen = new Set(existing.map((item) => item.id));
  const merged = [...existing];
  for (const item of incoming) {
    if (seen.has(item.id)) continue;
    seen.add(item.id);
    merged.push(item);
  }
  return merged;
}

function safeErrorMessage(error: unknown, fallback: string): string {
  const isKnownApiError =
    error instanceof ApiError ||
    (error instanceof Error && error.name === 'ApiError');
  if (isKnownApiError) {
    const code = (error as { code?: string }).code;
    if (code === 'ROW_VERSION_CONFLICT') {
      return '다른 사용자가 먼저 변경했습니다. 현재 입력은 유지되니 최신 정보를 확인한 뒤 다시 저장해주세요.';
    }
    if (error instanceof Error && error.message) return error.message;
  }
  return fallback;
}

function normalizeId(value: number | string | null | undefined): string | null {
  return value === null || value === undefined ? null : String(value);
}

function formatRecipientNo(value: string | null | undefined): string {
  return value?.trim() ? value : '미부여';
}

function formatNullable(value: string | null | undefined): string {
  return value?.trim() ? value : '없음';
}

function formatRecipientName(value: string | null | undefined): string {
  return value?.trim() ? value : '미입력';
}

/** Calendar Y/M/D in Asia/Seoul (not the host local timezone). */
function seoulCalendarParts(date: Date): { year: number; month: number; day: number } | null {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(date);
  const year = Number(parts.find((part) => part.type === 'year')?.value);
  const month = Number(parts.find((part) => part.type === 'month')?.value);
  const day = Number(parts.find((part) => part.type === 'day')?.value);
  if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) return null;
  return { year, month, day };
}

/** Korean counting age (세는나이): current Seoul year minus birth year plus one. */
function formatCountingAge(birthDate: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(birthDate)) return '미지정';
  const [yearStr, monthStr, dayStr] = birthDate.split('-');
  const birthYear = Number(yearStr);
  const birthMonth = Number(monthStr);
  const birthDay = Number(dayStr);
  const birthProbe = new Date(Date.UTC(birthYear, birthMonth - 1, birthDay));
  if (
    Number.isNaN(birthProbe.getTime()) ||
    birthProbe.getUTCFullYear() !== birthYear ||
    birthProbe.getUTCMonth() + 1 !== birthMonth ||
    birthProbe.getUTCDate() !== birthDay
  ) {
    return '미지정';
  }
  const currentYear = Number(
    new Intl.DateTimeFormat('en-US', { timeZone: 'Asia/Seoul', year: 'numeric' }).format(new Date()),
  );
  if (!Number.isFinite(currentYear)) return '미지정';
  return `${currentYear - birthYear + 1}세`;
}

/** International/Korean full age (만 나이): years since birth, minus 1 if birthday not yet reached. */
function formatInternationalAge(birthDate: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(birthDate)) return '미지정';
  const [yearStr, monthStr, dayStr] = birthDate.split('-');
  const birthYear = Number(yearStr);
  const birthMonth = Number(monthStr);
  const birthDay = Number(dayStr);
  // Birth dates are date-only; validate real calendar day without host-local wall time.
  const birthProbe = new Date(Date.UTC(birthYear, birthMonth - 1, birthDay));
  if (
    Number.isNaN(birthProbe.getTime()) ||
    birthProbe.getUTCFullYear() !== birthYear ||
    birthProbe.getUTCMonth() + 1 !== birthMonth ||
    birthProbe.getUTCDate() !== birthDay
  ) {
    return '미지정';
  }

  const seoul = seoulCalendarParts(new Date());
  if (!seoul) return '미지정';

  // Future relative to the current Asia/Seoul calendar day → 미지정.
  if (
    birthYear > seoul.year ||
    (birthYear === seoul.year && birthMonth > seoul.month) ||
    (birthYear === seoul.year && birthMonth === seoul.month && birthDay > seoul.day)
  ) {
    return '미지정';
  }

  let age = seoul.year - birthYear;
  const birthdayPassed =
    seoul.month > birthMonth || (seoul.month === birthMonth && seoul.day >= birthDay);
  if (!birthdayPassed) age -= 1;
  return age >= 0 ? `${age}세` : '미지정';
}

type BrowserLocation = {
  pathname: string;
  search: string;
};

function readBrowserLocation(): BrowserLocation {
  if (typeof window === 'undefined') return { pathname: '/recipients', search: '' };
  return {
    pathname: window.location.pathname || '/recipients',
    search: window.location.search,
  };
}

export const RecipientsPage = () => {
  const [location, setLocation] = useState<BrowserLocation>(readBrowserLocation);
  const listScrollRef = useRef<HTMLDivElement | null>(null);
  const listScrollTopRef = useRef(0);
  /** Last successfully loaded search/status key; used to detect filter resets. */
  const listFilterKeyRef = useRef<string | null>(null);
  /** Last successfully loaded API page for the current filter (append cursor). */
  const loadedPageRef = useRef(0);
  /** Monotonic generation: search/status/listReload bumps so late responses are ignored. */
  const listFetchGenRef = useRef(0);
  /** In-flight append guard (sync) so the same next page is not requested twice. */
  const listLoadingMoreRef = useRef(false);
  const listLoadMoreAbortRef = useRef<AbortController | null>(null);
  /** Tracks active detail id so late benefit-period responses do not clobber another recipient. */
  const activeIdRef = useRef<string | null>(null);
  const createOpenRef = useRef(false);
  const [recipientForm, setRecipientForm] = useState<RecipientFormState>(emptyRecipientForm);
  const [createOpen, setCreateOpen] = useState(false);
  const [detailExtrasOpen, setDetailExtrasOpen] = useState(false);
  const [detailBatchEditing, setDetailBatchEditing] = useState(false);
  const [detailBatchSaving, setDetailBatchSaving] = useState(false);
  const [detailBatchRevision, setDetailBatchRevision] = useState(0);
  const [createSaving, setCreateSaving] = useState(false);
  const [createMessage, setCreateMessage] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [listData, setListData] = useState<RecipientListResponse | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const [listLoadingMore, setListLoadingMore] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [listReload, setListReload] = useState(0);
  const [workspaceReload, setWorkspaceReload] = useState(0);
  const [detailRecipient, setDetailRecipient] = useState<Recipient | null>(null);
  const [detailForm, setDetailForm] = useState<RecipientFormState>(emptyRecipientForm);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailSaving, setDetailSaving] = useState(false);
  const [detailMessage, setDetailMessage] = useState<string | null>(null);
  const [detailStaleConflict, setDetailStaleConflict] = useState<RecipientStaleConflict | null>(null);
  const [guardians, setGuardians] = useState<Guardian[]>([]);
  const [guardianForms, setGuardianForms] = useState<GuardianFormSlots>(guardianFormsFromGuardians([]));
  const [guardianEditSnapshots, setGuardianEditSnapshots] = useState<GuardianFormSlots>(guardianFormsFromGuardians([]));
  const [editingGuardianIds, setEditingGuardianIds] = useState<[string | null, string | null]>([null, null]);
  const [guardianMessage, setGuardianMessage] = useState<string | null>(null);
  const [guardianError, setGuardianError] = useState<string | null>(null);
  /** Draft payer selection: null = self; 0/1 = guardian checkbox (mutual exclusive). */
  const [payerGuardianSlot, setPayerGuardianSlot] = useState<PayerGuardianSlot>(null);
  const [payerGuardianSlotSnapshot, setPayerGuardianSlotSnapshot] =
    useState<PayerGuardianSlot>(null);
  /** Single edit mode for recipient basic + both guardians + payer. */
  const [basicEditOpen, setBasicEditOpen] = useState(false);
  const [basicSaving, setBasicSaving] = useState(false);
  const [activeCopayPeriod, setActiveCopayPeriod] = useState<CopayPeriodSnapshot | null>(null);
  const [copayDraftCode, setCopayDraftCode] = useState<CopayBenefitCode>('GENERAL');
  const [copayDraftStartText, setCopayDraftStartText] = useState('');
  const [copaySaving, setCopaySaving] = useState(false);

  // Derive URL query state before any effect/callback that reads activeId so the
  // binding is not referenced in the temporal dead zone (tsc block-scoped error).
  const query = useMemo(() => new URLSearchParams(location.search), [location.search]);
  const search = query.get('search') ?? '';
  // URL may keep a display key (`filter`); server query must be `status`.
  const statusFilter = parseStatusFilter(query.get('status') ?? query.get('filter'));
  const selectedId = query.get('selected');
  const detailId = query.get('detail');
  const activeId = detailId ?? selectedId;
  activeIdRef.current = activeId;
  createOpenRef.current = createOpen;

  useEffect(() => {
    if (!activeId) {
      setActiveCopayPeriod(null);
      return undefined;
    }
    let cancelled = false;
    void listBenefitPeriods(activeId)
      .then((items) => {
        if (cancelled) return;
        setActiveCopayPeriod(effectiveCopayPeriod(items));
      })
      .catch(() => {
        if (!cancelled) setActiveCopayPeriod(null);
      });
    return () => {
      cancelled = true;
    };
  }, [activeId, workspaceReload]);

  useEffect(() => {
    if (!createOpen) return;
    setCopayDraftCode('GENERAL');
    setCopayDraftStartText('');
  }, [createOpen]);

  useEffect(() => {
    document.body.classList.toggle('recipient-detail-batch-managed', detailExtrasOpen);
    document.body.classList.toggle('recipient-detail-batch-editing', detailBatchEditing);
    return () => {
      document.body.classList.remove('recipient-detail-batch-managed');
      document.body.classList.remove('recipient-detail-batch-editing');
    };
  }, [detailBatchEditing, detailExtrasOpen]);

  useEffect(() => {
    if (!detailExtrasOpen || createOpen) return undefined;

    const managedForm = (target: EventTarget | null): HTMLFormElement | null => {
      if (!(target instanceof Element)) return null;
      const form = target.closest('form');
      if (!(form instanceof HTMLFormElement)) return null;
      if (
        form.matches('[data-testid="contract-create-form"]') ||
        form.querySelector('[data-detail-batch-field="true"]')
      ) {
        return form;
      }
      return null;
    };

    const handleClickCapture = (event: MouseEvent) => {
      const target = event.target instanceof Element ? event.target : null;
      const button = target?.closest('button');
      if (
        detailBatchEditing &&
        (button?.matches('[data-testid="recipient-detail-toggle"]') ||
          Boolean(target?.closest('.recipient-list-row')))
      ) {
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      if (button?.matches('[data-testid="recipient-basic-edit"]')) {
        event.preventDefault();
        event.stopPropagation();
        setDetailBatchEditing(true);
        return;
      }
      if (!detailBatchEditing && managedForm(event.target)) {
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      if (
        !detailBatchEditing &&
        button?.textContent?.trim() === '정정' &&
        button.closest('.recipient-w1c-panel')
      ) {
        event.preventDefault();
        event.stopPropagation();
      }
    };

    const handleSubmitCapture = (event: SubmitEvent) => {
      if (managedForm(event.target)) {
        event.preventDefault();
        event.stopPropagation();
      }
    };

    const handleKeydownCapture = (event: KeyboardEvent) => {
      if (!detailBatchEditing && managedForm(event.target)) {
        event.preventDefault();
        event.stopPropagation();
      }
    };

    document.addEventListener('click', handleClickCapture, true);
    document.addEventListener('submit', handleSubmitCapture, true);
    document.addEventListener('keydown', handleKeydownCapture, true);
    return () => {
      document.removeEventListener('click', handleClickCapture, true);
      document.removeEventListener('submit', handleSubmitCapture, true);
      document.removeEventListener('keydown', handleKeydownCapture, true);
    };
  }, [createOpen, detailBatchEditing, detailExtrasOpen]);

  useEffect(() => {
    const handlePopState = () => setLocation(readBrowserLocation());
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const cancelCreate = useCallback(() => {
    if (createSaving) return;
    setCreateOpen(false);
    setCreateError(null);
    setCreateMessage(null);
    setRecipientForm(emptyRecipientForm());
    setWorkspaceReload((current) => current + 1);
  }, [createSaving]);

  useEffect(() => {
    if (!createOpen) return;
    const handleCreateEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        cancelCreate();
      }
    };
    window.addEventListener('keydown', handleCreateEscape);
    return () => window.removeEventListener('keydown', handleCreateEscape);
  }, [cancelCreate, createOpen]);

  useEffect(() => {
    setDetailExtrasOpen(false);
  }, [activeId]);

  const updateQuery = useCallback(
    (updates: Record<string, string | null>, replace = true) => {
      const currentLocation = readBrowserLocation();
      const nextQuery = new URLSearchParams(currentLocation.search);
      Object.entries(updates).forEach(([key, value]) => {
        if (value === null || value === '') {
          nextQuery.delete(key);
        } else {
          nextQuery.set(key, value);
        }
      });
      const nextSearch = nextQuery.toString();
      const nextUrl = `${currentLocation.pathname}${nextSearch ? `?${nextSearch}` : ''}`;
      if (replace) {
        window.history.replaceState(window.history.state, '', nextUrl);
      } else {
        window.history.pushState(window.history.state, '', nextUrl);
      }
      window.dispatchEvent(new PopStateEvent('popstate'));
    },
    [],
  );

  // First screen must explicitly use status=ACTIVE in the URL (API default remains ALL when omitted).
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (!params.get('status') && !params.get('filter')) {
      updateQuery({ status: 'ACTIVE' }, true);
    }
  }, [location.search, updateQuery]);

  const selectedRecipient = useMemo(
    () =>
      (selectedId
        ? listData?.items.find((item) => normalizeId(item.id) === selectedId) ?? null
        : listData?.items[0] ?? null),
    [listData, selectedId],
  );

  // Server owns sort/filter/paging; client appends pages in response order.
  const visibleRecipients = listData?.items ?? [];
  const listTotal = listData?.total ?? 0;
  const listHasMore =
    listData != null &&
    typeof listData.total === 'number' &&
    Number.isFinite(listData.total) &&
    listData.items.length < listData.total;

  // First load / search / status / listReload: page 1 replace (reset cursor + rows on filter change).
  useEffect(() => {
    const controller = new AbortController();
    const filterKey = `${search}\0${statusFilter}`;
    const isFilterChange =
      listFilterKeyRef.current !== null && listFilterKeyRef.current !== filterKey;
    const fetchGen = ++listFetchGenRef.current;

    // Cancel any in-flight append so a late page-2 cannot land under a new filter.
    listLoadMoreAbortRef.current?.abort();
    listLoadMoreAbortRef.current = null;
    listLoadingMoreRef.current = false;
    setListLoadingMore(false);
    loadedPageRef.current = 0;

    setListLoading(true);
    setListError(null);
    // Drop prior projection immediately on search/status change so old
    // rows/total never sit under the new query while loading.
    if (isFilterChange) {
      setListData(null);
    }

    listRecipients({
      search,
      status: statusFilter,
      page: 1,
      pageSize: PAGE_SIZE,
      signal: controller.signal,
    })
      .then((response) => {
        if (fetchGen !== listFetchGenRef.current) return;
        if (!isValidListResponse(response)) {
          setListLoading(false);
          setListData(null);
          loadedPageRef.current = 0;
          setListError('수급자 목록 응답이 올바르지 않습니다.');
          return;
        }
        listFilterKeyRef.current = filterKey;
        loadedPageRef.current = response.page;
        setListData({
          items: response.items,
          total: response.total,
          page: response.page,
          page_size: response.page_size,
        });
        setListLoading(false);

        // After a search/status change, drop selected/detail that are not in the
        // first page (preserve search/status). Apply first-row selection when
        // selected is gone. Skip on initial load so deep-links remain.
        if (!isFilterChange) return;
        const current = new URLSearchParams(readBrowserLocation().search);
        const curSelected = current.get('selected');
        const curDetail = current.get('detail');
        const pageIds = new Set(
          response.items
            .map((item) => normalizeId(item.id))
            .filter((id): id is string => id !== null),
        );
        const updates: Record<string, string | null> = {};
        if (curSelected && !pageIds.has(curSelected)) {
          updates.selected = response.items.length
            ? normalizeId(response.items[0].id)
            : null;
        }
        if (curDetail && !pageIds.has(curDetail)) {
          updates.detail = null;
        }
        if (Object.keys(updates).length > 0) {
          updateQuery(updates, true);
        }
      })
      .catch((error: unknown) => {
        if (fetchGen !== listFetchGenRef.current || isAbortError(error)) return;
        setListLoading(false);
        setListData(null);
        loadedPageRef.current = 0;
        setListError(safeErrorMessage(error, '수급자 목록을 불러오지 못했습니다.'));
      });

    return () => {
      controller.abort();
    };
  }, [listReload, search, statusFilter, updateQuery]);

  const loadMoreRecipients = useCallback(() => {
    if (listLoading || listLoadingMoreRef.current) return;
    if (!listData || !listHasMore) return;
    if (typeof listData.total !== 'number' || !Number.isFinite(listData.total)) return;

    const nextPage = loadedPageRef.current + 1;
    if (nextPage < 2) return;

    const fetchGen = listFetchGenRef.current;
    const controller = new AbortController();
    // Single in-flight append: filter resets abort via listLoadMoreAbortRef.
    listLoadMoreAbortRef.current = controller;
    listLoadingMoreRef.current = true;
    setListLoadingMore(true);
    setListError(null);

    listRecipients({
      search,
      status: statusFilter,
      page: nextPage,
      pageSize: PAGE_SIZE,
      signal: controller.signal,
    })
      .then((response) => {
        if (fetchGen !== listFetchGenRef.current) return;
        if (!isValidListResponse(response)) {
          setListError('수급자 목록 응답이 올바르지 않습니다.');
          return;
        }
        setListData((current) => {
          if (!current || fetchGen !== listFetchGenRef.current) return current;
          const items = appendItemsById(current.items, response.items);
          loadedPageRef.current = response.page;
          return {
            items,
            total: response.total,
            page: response.page,
            page_size: response.page_size,
          };
        });
      })
      .catch((error: unknown) => {
        if (fetchGen !== listFetchGenRef.current || isAbortError(error)) return;
        // Keep already-loaded rows; surface append failure without inventing totals.
        setListError(safeErrorMessage(error, '수급자 목록을 더 불러오지 못했습니다.'));
      })
      .finally(() => {
        if (fetchGen !== listFetchGenRef.current) return;
        listLoadingMoreRef.current = false;
        setListLoadingMore(false);
        if (listLoadMoreAbortRef.current === controller) {
          listLoadMoreAbortRef.current = null;
        }
      });
  }, [listData, listHasMore, listLoading, search, statusFilter]);

  useEffect(() => {
    if (selectedId || !listData?.items.length) return;
    updateQuery({ selected: normalizeId(listData.items[0].id) }, true);
  }, [listData, selectedId, updateQuery]);

  useEffect(() => {
    const listNode = listScrollRef.current;
    if (listNode) listNode.scrollTop = listScrollTopRef.current;
  }, [detailId, location.search, visibleRecipients.length]);

  useEffect(() => {
    if (createOpen) return;
    setBasicEditOpen(false);
    setBasicSaving(false);
    setDetailStaleConflict(null);
    setPayerGuardianSlot(null);
    setPayerGuardianSlotSnapshot(null);
  }, [activeId]);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    if (createOpen) {
      setDetailLoading(false);
      return () => {
        cancelled = true;
        controller.abort();
      };
    }
    if (!activeId) {
      setDetailRecipient(null);
      setDetailForm(emptyRecipientForm());
      setGuardians([]);
      setGuardianForms(guardianFormsFromGuardians([]));
      setGuardianEditSnapshots(guardianFormsFromGuardians([]));
      setEditingGuardianIds([null, null]);
      setPayerGuardianSlot(null);
      setPayerGuardianSlotSnapshot(null);
      setBasicEditOpen(false);
      setDetailLoading(false);
      setDetailError(null);
      setDetailStaleConflict(null);
      return () => {
        cancelled = true;
        controller.abort();
      };
    }

    if (
      detailStaleConflict &&
      normalizeId(detailStaleConflict.latest.id) === activeId
    ) {
      setDetailLoading(false);
      return () => {
        cancelled = true;
        controller.abort();
      };
    }

    setDetailLoading(true);
    setDetailError(null);
    setGuardianError(null);
    setGuardianMessage(null);
    setDetailMessage(null);
    // Editable detail form requires a successful detail GET. Do not seed form/PATCH
    // state from list rows (list has no recipient_status; synthetic ACTIVE is unsafe).
    // Basic load uses only the recipient and its two guardian slots.
    setDetailRecipient(null);
    setDetailForm(emptyRecipientForm());
    setGuardians([]);
    setGuardianForms(guardianFormsFromGuardians([]));
    setGuardianEditSnapshots(guardianFormsFromGuardians([]));
    setEditingGuardianIds([null, null]);
    setPayerGuardianSlot(null);
    setPayerGuardianSlotSnapshot(null);
    setBasicEditOpen(false);

    Promise.allSettled([
      getRecipient(activeId, controller.signal),
      listGuardians(activeId, controller.signal),
    ]).then(([recipientResult, guardianResult]) => {
      if (cancelled) return; if (createOpenRef.current) { setDetailLoading(false); return; }

      const rawRecipient = valueFromResult(recipientResult);
      const embedded = (valueFromResult(recipientResult) as EmbeddedRecipient | undefined) ?? null;
      const embeddedGuardians = embedded?.guardians ?? [];
      const guardianResponse = valueFromResult(guardianResult);
      const resolvedGuardians = guardianResponse?.items ?? embeddedGuardians;
      const resolvedGuardianSlots = guardianSlotsFromGuardians(resolvedGuardians);

      const validated =
        rawRecipient && activeId
          ? validateDetailRecipient(rawRecipient, activeId)
          : null;

      if (validated) {
        setDetailRecipient(validated);
        setDetailForm(recipientFormFromRecipient(validated));
        setDetailStaleConflict(null);
      } else if (recipientResult.status === 'rejected') {
        setDetailRecipient(null);
        setDetailForm(emptyRecipientForm());
        setDetailError(safeErrorMessage(recipientResult.reason, '수급자 상세를 불러오지 못했습니다.'));
      } else {
        setDetailRecipient(null);
        setDetailForm(emptyRecipientForm());
        setDetailError(
          rawRecipient
            ? '수급자 상세 응답이 올바르지 않아 편집할 수 없습니다.'
            : '수급자 상세를 불러오지 못했습니다.',
        );
      }

      const nextGuardianIds: [string | null, string | null] = [
        resolvedGuardianSlots[0] ? normalizeId(resolvedGuardianSlots[0].id) : null,
        resolvedGuardianSlots[1] ? normalizeId(resolvedGuardianSlots[1].id) : null,
      ];
      const nextPayerSlot = payerSlotFromRecipient(validated, nextGuardianIds);
      setGuardians(resolvedGuardians);
      setGuardianForms(guardianFormsFromGuardians(resolvedGuardians));
      setGuardianEditSnapshots(guardianFormsFromGuardians(resolvedGuardians));
      setEditingGuardianIds(nextGuardianIds);
      setPayerGuardianSlot(nextPayerSlot);
      setPayerGuardianSlotSnapshot(nextPayerSlot);

      if (guardianResult.status === 'rejected' && !embeddedGuardians.length) {
        setGuardianError('보호자 정보를 불러오지 못했습니다.');
      }
      setDetailLoading(false);
    });

    return () => {
      cancelled = true;
      controller.abort();
    };
    // Do not depend on listData: successful detail PATCH updates the list row and
    // bumps listReload → new listData. Re-running this effect would clear
    // detailRecipient/form (and wipe 422 draft + role=alert errors) mid-edit, so
    // status-only follow-up PATCH and validation error UI would never land.
    // Detail reloads only on activeId change, explicit workspaceReload, or
    // stale-conflict lifecycle (detailStaleConflict).
  }, [activeId, detailStaleConflict, workspaceReload]);

  const captureRecipientStaleConflict = async (
    original: Recipient,
    draft: RecipientFormState,
    targetId: string,
  ): Promise<void> => {
    try {
      const rawLatest = await getRecipient(targetId);
      if (activeIdRef.current !== targetId || createOpenRef.current) return;
      const latest = validateDetailRecipient(rawLatest, targetId);
      if (!latest) {
        setDetailError('저장 충돌 후 대상 수급자의 최신 정보를 확인하지 못했습니다. 입력은 유지됩니다.');
        return;
      }

      const userChanged = new Set(changedRecipientFields(original, draft));
      const serverChanged = new Set(serverChangedRecipientFields(original, latest));
      const sameFields = [...userChanged].filter((field) => serverChanged.has(field));
      const sameFieldSet = new Set(sameFields);
      const draftValues = formComparableValues(draft);
      const latestValues = recipientComparableValues(latest);
      const sameFieldConflicts: RecipientFieldConflict[] = sameFields.map((field) => ({
        field,
        label: RECIPIENT_FIELD_LABELS[field],
        userValue: formatFieldDisplay(draftValues[field]),
        serverValue: formatFieldDisplay(latestValues[field]),
      }));

      if (sameFieldConflicts.length > 0) {
        // Same-field collision: server wins only for colliding fields; preserve disjoint user edits.
        // Active baseline/row_version become latest; next PATCH diffs current form vs that baseline.
        const merged = mergeUserChangesOntoLatest(latest, original, draft, sameFieldSet);
        setDetailRecipient(latest);
        setDetailForm(merged);
        setDetailStaleConflict({
          original,
          latest,
          draftAtConflict: draft,
          sameFieldConflicts,
          canAutoReapply: false,
        });
        setDetailError('이미 수정되었습니다');
        return;
      }

      // Different fields only: preserve user draft values on top of latest baseline.
      const merged = mergeUserChangesOntoLatest(latest, original, draft);
      setDetailRecipient(latest);
      setDetailForm(merged);
      setDetailStaleConflict({
        original,
        latest,
        draftAtConflict: draft,
        sameFieldConflicts: [],
        canAutoReapply: true,
      });
      setDetailError(
        '다른 사용자가 먼저 변경했습니다. 최신 서버값을 확인하고 필요한 변경만 다시 적용해주세요.',
      );
    } catch (error: unknown) {
      if (!isAbortError(error)) {
        setDetailError(
          safeErrorMessage(
            error,
            '저장 충돌 후 최신 수급자 정보를 불러오지 못했습니다. 입력은 유지됩니다.',
          ),
        );
      }
    }
  };

  const handleDetailReapply = async () => {
    if (!detailStaleConflict || !activeId || !detailStaleConflict.canAutoReapply) return;
    const reapplyTargetId = activeId;
    // Always diff the live form against the latest active baseline — never a stale pre-edit snapshot.
    const baseline = detailRecipient ?? detailStaleConflict.latest;
    const draft = detailForm;
    if (!draft.mobile_phone.trim()) {
      setDetailError('휴대전화를 입력해주세요.');
      return;
    }
    if (!recipientHasDraftChanges(baseline, draft)) {
      setDetailError(null);
      setDetailStaleConflict(null);
      return;
    }
    setDetailError(null);
    setDetailMessage(null);
    setDetailSaving(true);
    try {
      // Only fields that differ from the current latest baseline (post any user re-edit).
      const updatedRaw = await updateRecipient(
        activeId,
        recipientChangedFieldsPayload(baseline, draft, baseline.row_version),
      );
      if (activeIdRef.current !== reapplyTargetId || createOpenRef.current) return;
      const updated = validateDetailRecipient(updatedRaw, activeId);
      if (!updated) {
        setDetailError('다시 적용 응답이 올바르지 않습니다. 다시 불러와 주세요.');
        return;
      }
      setDetailRecipient(updated);
      setDetailForm(recipientFormFromRecipient(updated));
      setDetailStaleConflict(null);
      setDetailError(null);
      setDetailMessage('최신 버전에 변경 내용을 다시 적용했습니다.');
      setListData((current) =>
        current
          ? {
              ...current,
              items: current.items.map((item) =>
                normalizeId(item.id) === activeId
                  ? mergeRecipientIntoListItem(item, updated)
                  : item,
              ),
            }
          : current,
      );
      setListReload((current) => current + 1);
    } catch (error: unknown) {
      if (!isAbortError(error)) {
        if (isApiErrorCode(error, 'ROW_VERSION_CONFLICT')) {
          await captureRecipientStaleConflict(baseline, draft, reapplyTargetId);
        } else {
          setDetailError(safeErrorMessage(error, '변경 내용을 다시 적용하지 못했습니다.'));
        }
      }
    } finally {
      setDetailSaving(false);
    }
  };

  const setPayerSlotExclusive = (slot: GuardianSlot, checked: boolean) => {
    setPayerGuardianSlot((current) => {
      if (checked) return slot;
      // Unchecking the active payer slot falls back to recipient self.
      if (current === slot) return null;
      return current;
    });
  };

  const cancelBasicEdit = () => {
    if (basicSaving) return;
    if (detailRecipient) {
      setDetailForm(recipientFormFromRecipient(detailRecipient));
    }
    setGuardianForms(guardianEditSnapshots);
    setPayerGuardianSlot(payerGuardianSlotSnapshot);
    setBasicEditOpen(false);
    setDetailError(null);
    setDetailMessage(null);
    setGuardianError(null);
    setGuardianMessage(null);
  };

  const handleDetailBatchSave = async () => {
    if (!activeId || detailBatchSaving) return;

    const input = (testId: string) =>
      document.querySelector<HTMLInputElement>(`[data-testid="${testId}"]`);
    const select = (testId: string) =>
      document.querySelector<HTMLSelectElement>(`[data-testid="${testId}"]`);
    const nullable = (value: string | undefined) => value?.trim() || null;
    const mutation = <T extends object>(
      marker: HTMLInputElement,
      payload: T,
    ): { period_id?: number; payload: T & { expected_row_version?: number } } => {
      const periodId = Number(marker.dataset.periodId || 0);
      if (!periodId) return { payload };
      const rowVersion = Number(marker.dataset.rowVersion || 0);
      if (!rowVersion) throw new Error('정정 대상의 버전 정보를 다시 불러와주세요.');
      return {
        period_id: periodId,
        payload: { ...payload, expected_row_version: rowVersion },
      };
    };

    try {
      const payload: RecipientDetailBatchRequest = {};
      const identity = input('w1c-certification-input');
      if (identity?.value.trim()) {
        payload.certification_identity = { certification_number: identity.value.trim() };
      }

      const certificationStart = input('w1c-certification-start-date');
      const certificationEnd = input('w1c-certification-end-date');
      const certificationGrade = select('w1c-certification-grade-select');
      if (certificationGrade?.value && certificationStart?.value && certificationEnd?.value) {
        payload.certification_period = mutation(certificationStart, {
          grade_code: certificationGrade.value,
          start_date: certificationStart.value,
          end_date: certificationEnd.value,
        });
      }

      const benefitCode = select('w1c-benefit-select');
      const benefitStartText = input('w1c-benefit-start-text');
      if (benefitCode?.value && benefitStartText) {
        payload.benefit_period = mutation(benefitStartText, {
          benefit_code: benefitCode.value,
          start_text: benefitStartText.value,
        });
      }

      const approvalAmount = input('w1c-approval-amount-input');
      const approvalStart = input('w1c-approval-start-date');
      const approvalEnd = input('w1c-approval-end-date');
      if (approvalAmount?.value.trim() && approvalStart?.value) {
        const amount = normalizeApprovalAmountKrw(approvalAmount.value);
        if (amount === null) {
          throw new Error(
            '승인금액은 0 이상 9,223,372,036,854,775,807 이하의 정수 원 단위로 입력해주세요.',
          );
        }
        payload.approval_amount_period = mutation(approvalStart, {
          amount_krw: amount,
          start_date: approvalStart.value,
          end_date: nullable(approvalEnd?.value),
        });
      }

      const contractStart = input('contract-start-date-input');
      const contractServiceType = select('contract-service-type-select');
      if (contractStart?.value && contractServiceType?.value) {
        payload.contract = {
          service_type_code: contractServiceType.value,
          start_date: contractStart.value,
          end_date: nullable(input('contract-end-date-input')?.value),
          service_start_date: nullable(input('contract-service-start-date-input')?.value),
          end_reason_text: nullable(input('contract-end-reason-input')?.value),
        };
      }

      if (!Object.keys(payload).length) {
        window.alert('변경된 상세 정보가 없습니다.');
        return;
      }

      setDetailBatchSaving(true);
      await saveRecipientDetailBatch(Number(activeId), payload);
      setDetailBatchEditing(false);
      setDetailBatchRevision((current) => current + 1);
      setListReload((current) => current + 1);
      setWorkspaceReload((current) => current + 1);
    } catch (error: unknown) {
      window.alert(safeErrorMessage(error, '상세 정보를 저장하지 못했습니다.'));
    } finally {
      setDetailBatchSaving(false);
    }
  };

  const cancelDetailBatchEdit = () => {
    if (detailBatchSaving) return;
    setDetailBatchEditing(false);
    setDetailBatchRevision((current) => current + 1);
  };

  const handleAtomicCreateSave = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!createOpen || createSaving) return;
    setCreateMessage(null);
    setCreateError(null);
    if (!recipientForm.mobile_phone.trim()) {
      window.alert('휴대전화를 입력해주세요.');
      return;
    }
    const guardianMutations: BasicGuardianMutation[] = [];
    for (const slot of [0, 1] as GuardianSlot[]) {
      const form = guardianForms[slot];
      if (!guardianSlotHasContent(form) && payerGuardianSlot !== slot) continue;
      guardianMutations.push({ slot, payload: guardianPayload(form) });
    }
    if (payerGuardianSlot === 'unlisted') {
      window.alert('등록 화면에서는 보호자1 또는 보호자2를 납부자로 선택해주세요.');
      return;
    }
    if (
      payerGuardianSlot !== null &&
      !guardianMutations.some((mutation) => mutation.slot === payerGuardianSlot)
    ) {
      window.alert('납부자로 선택한 보호자 정보를 다시 확인해주세요.');
      return;
    }

    setCreateSaving(true);
    setCopaySaving(true);
    try {
      const result = await createRecipientBasicBatch({
        recipient: recipientCreatePayload(recipientForm),
        guardians: guardianMutations,
        payer_guardian_slot: payerGuardianSlot,
      });
      setCreateMessage('수급자·보호자 정보를 저장했습니다. 일반 혜택은 자동 생성되었습니다.');
      setCreateOpen(false);
      setRecipientForm(emptyRecipientForm());
      setGuardianForms([emptyGuardianForm(), emptyGuardianForm()]);
      setEditingGuardianIds([null, null]);
      setPayerGuardianSlot(null);
      setListReload((current) => current + 1);
      setWorkspaceReload((current) => current + 1);
      openDetail(result.recipient.id);
    } catch (error: unknown) {
      const message = safeErrorMessage(error, '수급자 정보를 저장하지 못했습니다.');
      setCreateError(message);
      window.alert(message);
    } finally {
      setCopaySaving(false);
      setCreateSaving(false);
    }
  };

  const handleAtomicBasicSave = async () => {
    if (!detailRecipient || !activeId || detailLoading || basicSaving || !basicEditOpen) return;
    const saveTargetId = activeId;
    if (!detailForm.mobile_phone.trim()) {
      window.alert('휴대전화를 입력해주세요.');
      return;
    }
    const guardianMutations: BasicGuardianMutation[] = [];
    for (const slot of [0, 1] as GuardianSlot[]) {
      const form = guardianForms[slot];
      const existingId = editingGuardianIds[slot];
      if (!existingId && !guardianSlotHasContent(form) && payerGuardianSlot !== slot) continue;
      if (existingId) {
        const existing = guardians.find((guardian) => normalizeId(guardian.id) === existingId);
        if (!existing) {
          window.alert(`보호자${slot + 1}의 최신 정보를 다시 불러와 주세요.`);
          return;
        }
        guardianMutations.push({
          slot,
          guardian_id: Number(existing.id),
          payload: {
            ...guardianPayload(form),
            expected_row_version: existing.row_version,
          },
        });
      } else {
        guardianMutations.push({ slot, payload: guardianPayload(form) });
      }
    }
    if (
      payerGuardianSlot !== null &&
      payerGuardianSlot !== 'unlisted' &&
      !guardianMutations.some((mutation) => mutation.slot === payerGuardianSlot)
    ) {
      window.alert('납부자로 선택한 보호자 정보를 다시 확인해주세요.');
      return;
    }

    setDetailError(null);
    setDetailMessage(null);
    setGuardianError(null);
    setBasicSaving(true);
    setDetailSaving(true);
    setCopaySaving(true);
    const baselineRecipient = detailRecipient;
    const draftAtSave = detailForm;
    try {
      const result = await updateRecipientBasicBatch(Number(activeId), {
        recipient: recipientChangedFieldsPayload(
          baselineRecipient,
          draftAtSave,
          baselineRecipient.row_version,
        ),
        guardians: guardianMutations,
        payer_guardian_slot: payerGuardianSlot === 'unlisted' ? null : payerGuardianSlot,
        preserve_payer: payerGuardianSlot === 'unlisted',
        benefit_period: copayDraftDirty
          ? buildCopayBenefitMutations(activeCopayPeriod, {
              code: copayDraftCode,
              startText: copayDraftStartText,
            })
          : undefined,
      });
      if (activeIdRef.current !== saveTargetId || createOpenRef.current) return;
      const updated = validateDetailRecipient(result.recipient, activeId);
      if (updated) {
        setDetailRecipient(updated);
        setDetailForm(recipientFormFromRecipient(updated));
      }
      const nextGuardians = result.guardians ?? [];
      const nextGuardianSlots = guardianSlotsFromGuardians(nextGuardians);
      const nextGuardianIds: [string | null, string | null] = [
        nextGuardianSlots[0] ? normalizeId(nextGuardianSlots[0].id) : null,
        nextGuardianSlots[1] ? normalizeId(nextGuardianSlots[1].id) : null,
      ];
      setGuardians(nextGuardians);
      setGuardianForms(guardianFormsFromGuardians(nextGuardians));
      setGuardianEditSnapshots(guardianFormsFromGuardians(nextGuardians));
      setEditingGuardianIds(nextGuardianIds);
      const nextPayer = payerSlotFromRecipient(updated, nextGuardianIds);
      setPayerGuardianSlot(nextPayer);
      setPayerGuardianSlotSnapshot(nextPayer);
      setDetailStaleConflict(null);
      setGuardianError(null);
      setGuardianMessage(null);
      setBasicEditOpen(false);
      setDetailMessage('수급자·보호자·혜택 정보를 저장했습니다.');
      setListReload((current) => current + 1);
      // Do not bump workspaceReload here: the batch response already has the latest
      // recipient/guardians/payer. A full workspace reload would clear detailMessage and
      // wipe the just-applied state (and leave empty guardians if the follow-up GET fails).
      // Benefit periods are not returned by basic-batch; refresh that baseline only.
      // Guard against race: if user navigates to another recipient before this lands,
      // do not overwrite that recipient's copay baseline (same pattern as the activeId effect).
      const benefitRefreshId = activeId;
      void listBenefitPeriods(benefitRefreshId)
        .then((items) => {
          if (activeIdRef.current !== benefitRefreshId) return;
          setActiveCopayPeriod(effectiveCopayPeriod(items));
        })
        .catch(() => {
          // Keep previous copay baseline; list projection still refreshes via listReload.
        });
    } catch (error: unknown) {
      if (isAbortError(error)) {
        return;
      }
      if (isApiErrorCode(error, 'ROW_VERSION_CONFLICT')) {
        // Prefer server-provided details.entity so basic-batch can distinguish
        // recipient vs guardian vs benefit_period conflicts. Fall back to draft
        // inference when entity is absent (older servers) or an unexpected value.
        const conflictEntity =
          error instanceof ApiError && typeof error.details?.entity === 'string'
            ? error.details.entity
            : (error as { details?: { entity?: unknown } }).details?.entity;
        const entity =
          typeof conflictEntity === 'string' ? conflictEntity : undefined;

        const reloadGuardiansAfterConflict = async () => {
          try {
            const response = await listGuardians(activeId);
            if (activeIdRef.current !== saveTargetId || createOpenRef.current) return;
            const items = response.items ?? [];
            const itemSlots = guardianSlotsFromGuardians(items);
            const nextGuardianIds: [string | null, string | null] = [
              itemSlots[0] ? normalizeId(itemSlots[0].id) : null,
              itemSlots[1] ? normalizeId(itemSlots[1].id) : null,
            ];
            setGuardians(items);
            setGuardianForms(guardianFormsFromGuardians(items));
            setGuardianEditSnapshots(guardianFormsFromGuardians(items));
            setEditingGuardianIds(nextGuardianIds);
            setGuardianError('보호자 정보가 다른 곳에서 변경되어 최신 정보를 불러왔습니다.');
          } catch (reloadError: unknown) {
            setGuardianError(
              safeErrorMessage(
                reloadError,
                '보호자 충돌 후 최신 정보를 불러오지 못했습니다. 입력은 유지됩니다.',
              ),
            );
          }
        };

        const reloadBenefitPeriodAfterConflict = async () => {
          const conflictId = activeId;
          try {
            const items = await listBenefitPeriods(conflictId);
            if (activeIdRef.current !== conflictId) return;
            const latest = effectiveCopayPeriod(items);
            setActiveCopayPeriod(latest);
            setCopayDraftCode(normalizeCopayBenefitCode(latest?.benefit_code));
            setCopayDraftStartText(latest?.start_text ?? '');
            setDetailError(
              '본인부담금 정보가 다른 곳에서 변경되어 최신 정보를 불러왔습니다.',
            );
          } catch (reloadError: unknown) {
            if (activeIdRef.current !== conflictId) return;
            setDetailError(
              safeErrorMessage(
                reloadError,
                '본인부담금 충돌 후 최신 정보를 불러오지 못했습니다. 입력은 유지됩니다.',
              ),
            );
          }
        };

        if (entity === 'recipient') {
          await captureRecipientStaleConflict(baselineRecipient, draftAtSave, saveTargetId);
        } else if (entity === 'guardian') {
          await reloadGuardiansAfterConflict();
        } else if (entity === 'benefit_period') {
          await reloadBenefitPeriodAfterConflict();
        } else {
          const hadRecipientChanges = recipientHasDraftChanges(
            baselineRecipient,
            draftAtSave,
          );
          if (hadRecipientChanges) {
            await captureRecipientStaleConflict(baselineRecipient, draftAtSave, saveTargetId);
          } else {
            await reloadGuardiansAfterConflict();
          }
        }
        return;
      }
      const message = safeErrorMessage(error, '수급자·보호자 정보를 저장하지 못했습니다.');
      setDetailError(message);
      window.alert(message);
    } finally {
      setCopaySaving(false);
      setDetailSaving(false);
      setBasicSaving(false);
    }
  };

  const beginBasicEdit = () => {
    if (!detailRecipient || detailLoading || basicSaving || createOpen) return;
    setGuardianEditSnapshots(guardianForms);
    setPayerGuardianSlotSnapshot(payerGuardianSlot);
    setDetailError(null);
    setDetailMessage(null);
    setGuardianError(null);
    setGuardianMessage(null);
    setCopayDraftCode(
      normalizeCopayBenefitCode(activeCopayPeriod?.benefit_code ?? detailListProjection?.benefit_code),
    );
    setCopayDraftStartText(activeCopayPeriod?.start_text ?? '');
    setDetailExtrasOpen(false);
    setBasicEditOpen(true);
  };

  const openDetail = (recipientId: number | string) => {
    const nextSelected = normalizeId(recipientId);
    updateQuery(
      {
        selected: nextSelected,
        detail: normalizeId(recipientId),
      },
      false,
    );
  };

  const handleListScroll = (event: UIEvent<HTMLDivElement>) => {
    const target = event.currentTarget;
    listScrollTopRef.current = target.scrollTop;
    const remaining = target.scrollHeight - target.scrollTop - target.clientHeight;
    // Near bottom of the list panel (not window): request next page.
    if (remaining <= 80) {
      loadMoreRecipients();
    }
  };

  const activeListRecipient = useMemo(
    () =>
      listData?.items.find((item) => normalizeId(item.id) === activeId) ??
      null,
    [activeId, listData],
  );
  // Grade/copay live only on list projection. Use them solely when the list row id
  // matches the active detail target — never fall back to selectedRecipient (first-row).
  const detailListProjection =
    activeListRecipient && activeId && normalizeId(activeListRecipient.id) === activeId
      ? activeListRecipient
      : null;
  // Summary panel may use list identity for non-status display only.
  // Editable detail form requires detailRecipient from a successful detail GET.
  const detailViewRecipient =
    detailRecipient && normalizeId(detailRecipient.id) === activeId
      ? detailRecipient
      : activeListRecipient
        ? recipientIdentityFromListItem(activeListRecipient)
        : detailId
          ? null
          : selectedRecipient
            ? recipientIdentityFromListItem(selectedRecipient)
            : null;
  // Form only after successful detail GET (detailRecipient never seeded from list).
  // PATCH/validation errors keep detailRecipient so draft remains editable.
  const detailFormReady =
    Boolean(detailRecipient) &&
    normalizeId(detailRecipient?.id) === activeId &&
    !detailLoading;
  const inputsLocked = basicSaving || detailSaving || detailLoading;
  const payerSelfLabel = '납부자(기본) · 수급자 본인';
  const payerCurrentLabel =
    payerGuardianSlot === 0
      ? '납부자 · 보호자1'
      : payerGuardianSlot === 1
        ? '납부자 · 보호자2'
        : payerGuardianSlot === 'unlisted'
          ? '납부자 · 목록 외 보호자'
          : payerSelfLabel;
  const guardianDraftDirty =
    !guardianFormsEqual(guardianForms[0], guardianEditSnapshots[0]) ||
    !guardianFormsEqual(guardianForms[1], guardianEditSnapshots[1]);
  const payerDraftDirty = payerGuardianSlot !== payerGuardianSlotSnapshot;
  // Same dirty condition as handleAtomicBasicSave benefit_period — name-only saves must not invent a change.
  const copayDraftDirty =
    copayDraftCode !==
      normalizeCopayBenefitCode(activeCopayPeriod?.benefit_code ?? detailListProjection?.benefit_code) ||
    copayDraftStartText !== (activeCopayPeriod?.start_text ?? '');
  const basicSaveEnabled =
    detailFormReady &&
    basicEditOpen &&
    !inputsLocked &&
    Boolean(detailRecipient) &&
    (recipientHasDraftChanges(detailRecipient!, detailForm) ||
      guardianDraftDirty ||
      payerDraftDirty ||
      copayDraftDirty);
  return (
    <div className="recipients-page" data-testid="page-recipients">
      <div className="recipient-page-heading">
        <div>
          <h1>수급자 관리</h1>
        </div>
        <div
          className="recipient-page-status"
          data-testid="recipient-list-status"
          aria-live="polite"
        >
          {listLoading ? (
            <span className="recipient-status recipient-status-loading">목록 불러오는 중</span>
          ) : listError ? (
            <span className="recipient-status recipient-status-error">목록 확인 필요</span>
          ) : null}
        </div>
      </div>

      <div className="recipient-workspace-grid">
        <section className="recipient-list-panel" data-testid="recipient-list">
          <h2 className="visually-hidden">수급자 목록</h2>

          <div className="recipient-list-controls">
            <label className="recipient-field recipient-search-field">
              <span className="visually-hidden">검색</span>
              <input
                data-testid="recipient-search-input"
                value={search}
                onChange={(event) =>
                  updateQuery({ search: event.target.value, page: null }, true)
                }
                placeholder="이름 검색"
              />
            </label>
            <label className="recipient-field recipient-filter-field">
              <span className="visually-hidden">상태</span>
              <select
                data-testid="recipient-filter-select"
                value={statusFilter}
                onChange={(event) =>
                  updateQuery(
                    {
                      status: event.target.value,
                      filter: null,
                      page: null,
                    },
                    true,
                  )
                }
              >
                {LIST_STATUS_FILTERS.map((value) => (
                  <option key={value} value={value}>
                    {LIST_STATUS_LABELS[value]}
                  </option>
                ))}
              </select>
            </label>
            <span className="recipient-count" data-testid="recipient-count" aria-live="polite">
              총 {listTotal}명
            </span>
          </div>

          <div className="recipient-list-header" data-testid="recipient-list-header">
            <span>등급</span>
            <span>이름</span>
            <span>나이</span>
            <span>본·부%</span>
            <span>제공중 서비스</span>
          </div>

          <span className="visually-hidden" data-testid="recipient-selected-name">
            {selectedRecipient
              ? formatRecipientName(selectedRecipient.name)
              : selectedId
                ? '현재 페이지에 없음'
                : '없음'}
          </span>

          <div
            ref={listScrollRef}
            className="recipient-list-scroll"
            data-testid="recipient-list-scroll"
            onScroll={handleListScroll}
          >
            {listLoading && !visibleRecipients.length ? (
              <div className="recipient-list-row recipient-list-row-placeholder">
                <span data-testid="recipient-list-loading">목록을 불러오는 중입니다.</span>
              </div>
            ) : null}
            {listError ? (
              <div className="recipient-inline-error" role="alert">
                {listError}
              </div>
            ) : null}
            {!listLoading && !listError && !visibleRecipients.length ? (
              <div className="recipient-empty-state">등록된 수급자가 없습니다.</div>
            ) : null}
            {visibleRecipients.map((recipient) => {
              const id = normalizeId(recipient.id);
              const isSelected = id === selectedId;
              const servicesLabel = formatListServices(recipient.services);
              const benefitLabel = formatBenefitCode(recipient.benefit_code);
              const copayLabel = formatCopaymentRate(recipient.copayment_rate);
              const gradeLabel = formatGradeCode(recipient.grade_code);
              return (
                <button
                  className={`recipient-list-row${isSelected ? ' is-selected' : ''}`}
                  data-testid="recipient-name-option"
                  key={id}
                  type="button"
                  onClick={() => openDetail(recipient.id)}
                >
                  <span
                    className="recipient-list-cell recipient-list-grade"
                    data-testid="recipient-list-grade"
                  >
                    {gradeLabel}
                  </span>
                  <span className="recipient-list-row-main">
                    <strong>{formatRecipientName(recipient.name)}</strong>
                    <span className="visually-hidden">
                      {recipient.birth_date} · {recipient.sex_code}
                    </span>
                    <span className="visually-hidden">주소: <span data-testid="recipient-list-address">{formatNullable(recipient.address)}</span></span>
                    <span className="visually-hidden">휴대전화: <span data-testid="recipient-list-mobile-phone">{formatNullable(recipient.mobile_phone)}</span></span>
                  </span>
                  <span className="recipient-list-cell recipient-list-age" data-testid="recipient-list-age">
                    {formatCountingAge(recipient.birth_date ?? '')}
                  </span>
                  <span
                    className="recipient-list-cell recipient-list-copay"
                    data-testid="recipient-list-copay"
                    title={`급여 ${benefitLabel} · 본인부담 ${copayLabel}`}
                  >
                    <span data-testid="recipient-list-benefit">{benefitLabel}</span>
                    <span className="recipient-list-copay-sep" aria-hidden="true">
                      ·
                    </span>
                    <span data-testid="recipient-list-copay-rate">{copayLabel}</span>
                  </span>
                  <span
                    className="recipient-list-cell recipient-list-services"
                    data-testid="recipient-list-services"
                    title={servicesLabel}
                  >
                    {servicesLabel}
                  </span>
                  <span className="visually-hidden recipient-list-row-meta">
                    <span data-testid="recipient-list-recipient-no">
                      {formatRecipientNo(recipient.recipient_no)}
                    </span>
                  </span>
                </button>
              );
            })}
            {listLoadingMore ? (
              <div className="recipient-list-row recipient-list-row-placeholder">
                <span data-testid="recipient-list-loading-more">목록을 더 불러오는 중입니다.</span>
              </div>
            ) : null}
          </div>

        </section>

        <section
          className={`recipient-detail-panel${activeId ? '' : ' is-idle'}${createOpen ? ' is-creating' : ''}`}
          data-testid="recipient-detail-workspace"
        >
          <div className="recipient-detail-heading">
            <div className="recipient-detail-title">
              <h2>
                {detailViewRecipient ? formatRecipientName(detailViewRecipient.name) : '수급자 정보'}
              </h2>
              <span className="recipient-detail-recipient-no">
                <span>수급자번호</span>
                <strong data-testid="recipient-detail-recipient-no">
                  {formatRecipientNo(detailViewRecipient?.recipient_no)}
                </strong>
              </span>
            </div>
            <div className="recipient-create-actions">
            {!createOpen ? (
              <button
                className="recipient-secondary-button recipient-detail-toggle"
                data-testid="recipient-detail-toggle"
                type="button"
                aria-expanded={detailExtrasOpen}
                onClick={() => {
                  if (basicEditOpen) return;
                  setDetailExtrasOpen((current) => !current);
                }}
                disabled={basicEditOpen || detailBatchEditing || inputsLocked}
              >
                {detailExtrasOpen ? '기본정보' : '상세'}
              </button>
            ) : null}
            {!createOpen && activeId ? (
              basicEditOpen ? (
                <>
                  <button
                    className="recipient-secondary-button"
                    data-testid="recipient-basic-save"
                    type="button"
                    onClick={() => void handleAtomicBasicSave()}
                    disabled={!basicSaveEnabled}
                  >
                    {basicSaving ? '저장 중…' : '저장'}
                  </button>
                  <button
                    className="recipient-secondary-button"
                    data-testid="recipient-basic-cancel"
                    type="button"
                    onClick={() => {
                      cancelBasicEdit();
                    }}
                    disabled={inputsLocked}
                  >
                    취소
                  </button>
                </>
              ) : (
                <button
                  className="recipient-secondary-button"
                  data-testid="recipient-basic-edit"
                  type="button"
                  onClick={beginBasicEdit}
                  disabled={inputsLocked || createOpen}
                >
                  수정
                </button>
              )
            ) : null}
            {!detailExtrasOpen || createOpen ? (
              <button
                className="recipient-secondary-button recipient-create-trigger"
                data-testid="recipient-create-toggle"
                form={createOpen ? 'recipient-create-form' : undefined}
                type={createOpen ? 'submit' : 'button'}
                aria-expanded={createOpen}
                onClick={createOpen ? undefined : (event) => {
                  event.preventDefault();
                  setCreateError(null);
                  setCreateMessage(null);
                  setRecipientForm(emptyRecipientForm());
                  setGuardianForms([emptyGuardianForm(), emptyGuardianForm()]);
                  setEditingGuardianIds([null, null]);
                  setPayerGuardianSlot(null);
                  setDetailExtrasOpen(false);
                  setBasicEditOpen(false);
                  setDetailStaleConflict(null);
                  setDetailLoading(false);
                  setCreateOpen(true);
                }}
                disabled={basicEditOpen || basicSaving}
              >
                {createOpen ? '저장' : '수급자 등록'}
              </button>
            ) : null}
            {createOpen ? (
              <button
                className="recipient-secondary-button recipient-create-cancel"
                data-testid="recipient-create-cancel"
                type="button"
                onClick={cancelCreate}
                disabled={createSaving}
              >
                취소
              </button>
            ) : null}
            </div>
          </div>

          {!activeId ? (
            <div className="recipient-idle-message">목록에서 수급자를 선택하세요.</div>
          ) : null}

          {detailLoading ? <div className="recipient-inline-note">상세 정보를 불러오는 중입니다.</div> : null}
          {/* Single accessible alert: non-conflict errors only. Stale conflict owns its own alert. */}
          {detailError && !detailStaleConflict ? (
            <div className="recipient-inline-error" role="alert">
              {detailError}
            </div>
          ) : null}

          {!detailExtrasOpen ? (
            <>
          <section className={`recipient-basic-section${createOpen || basicEditOpen ? ' is-editing' : ''}`}>
            <form
              id={createOpen ? 'recipient-create-form' : undefined}
              className="recipient-detail-summary recipient-basic-summary"
              inert={!createOpen && !basicEditOpen ? true : undefined}
              data-testid={
                createOpen
                  ? 'recipient-create-form'
                  : basicEditOpen
                    ? 'recipient-basic-edit-summary'
                    : 'recipient-basic-view-summary'
              }
              noValidate
              onSubmit={(event) => {
                if (createOpen) {
                  void handleAtomicCreateSave(event);
                  return;
                }
                event.preventDefault();
              }}
            >
              <div className="recipient-summary-item">
                <span>이름</span>
                {activeId || createOpen || basicEditOpen ? (
                  <input
                    className="recipient-summary-control"
                    data-testid={createOpen ? 'recipient-name-input' : 'recipient-detail-name-input'}
                    value={createOpen ? recipientForm.name : detailForm.name}
                    placeholder={
                      !createOpen && !detailForm.name.trim() ? '미입력' : undefined
                    }
                    onFocus={basicEditOpen ? (event) => event.currentTarget.select() : undefined}
                    onChange={(event) => {
                      if (createOpen) {
                        setRecipientForm((current) => ({ ...current, name: event.target.value }));
                        return;
                      }
                      setDetailForm((current) => ({ ...current, name: event.target.value }));
                    }}
                    disabled={basicEditOpen && inputsLocked}
                  />
                ) : (
                  <strong>{formatRecipientName(detailViewRecipient?.name)}</strong>
                )}
              </div>

              <div className="recipient-summary-item">
                <span>생년월일</span>
                {activeId || createOpen || basicEditOpen ? (
                  <input
                    className="recipient-summary-control"
                    data-testid={createOpen ? 'recipient-birth-date-input' : 'recipient-detail-birth-date-input'}
                    type="date"
                    inputMode="numeric"
                    value={createOpen ? recipientForm.birth_date : detailForm.birth_date}
                    onChange={(event) => {
                      if (createOpen) {
                        setRecipientForm((current) => ({ ...current, birth_date: event.target.value }));
                        return;
                      }
                      setDetailForm((current) => ({ ...current, birth_date: event.target.value }));
                    }}
                    disabled={basicEditOpen && inputsLocked}
                  />
                ) : (
                  <strong>{detailViewRecipient?.birth_date ?? '없음'}</strong>
                )}
              </div>

              <div className="recipient-summary-item">
                <span>만 나이</span>
                <strong data-testid={createOpen ? undefined : 'recipient-detail-international-age'}>
                  {formatInternationalAge(
                    createOpen
                      ? recipientForm.birth_date
                      : basicEditOpen
                        ? detailForm.birth_date
                        : detailViewRecipient?.birth_date ?? '',
                  )}
                </strong>
              </div>

              <div className="recipient-summary-item">
                <span>성별</span>
                {activeId || createOpen || basicEditOpen ? (
                  <select
                    className="recipient-summary-control"
                    data-testid={createOpen ? 'recipient-sex-code-select' : 'recipient-detail-sex-code-select'}
                    value={createOpen ? recipientForm.sex_code : detailForm.sex_code}
                    onChange={(event) => {
                      const sexCode = event.target.value as RecipientSexCode | '';
                      if (createOpen) {
                        setRecipientForm((current) => ({ ...current, sex_code: sexCode }));
                        return;
                      }
                      setDetailForm((current) => ({ ...current, sex_code: sexCode }));
                    }}
                    disabled={basicEditOpen && inputsLocked}
                  >
                    <option value="">미입력</option>
                    <option value="MALE">남성</option>
                    <option value="FEMALE">여성</option>
                  </select>
                ) : (
                  <strong>
                    {detailViewRecipient?.sex_code === 'MALE'
                      ? '남성'
                      : detailViewRecipient?.sex_code === 'FEMALE'
                        ? '여성'
                        : '없음'}
                  </strong>
                )}
              </div>

              <div className="recipient-summary-item">
                <span>등급</span>
                <strong data-testid={createOpen ? 'recipient-create-grade' : 'recipient-detail-grade'}>
                  {createOpen ? '미지정' : formatGradeCode(detailListProjection?.grade_code)}
                </strong>
              </div>

              <div className="recipient-summary-item">
                <span>인정번호</span>
                <strong
                  data-testid={
                    createOpen ? 'recipient-create-certification-number' : 'recipient-detail-certification-number'
                  }
                >
                  미지정
                </strong>
              </div>

              <div className="recipient-summary-item">
                <span>휴대전화</span>
                {activeId || createOpen || basicEditOpen ? (
                  <input
                    className="recipient-summary-control"
                    data-testid={createOpen ? 'recipient-mobile-phone-input' : 'recipient-detail-mobile-phone-input'}
                    inputMode="tel"
                    placeholder={createOpen ? '010-0000-0000' : undefined}
                    maxLength={13}
                    value={createOpen ? recipientForm.mobile_phone : detailForm.mobile_phone}
                    onFocus={basicEditOpen ? (event) => event.currentTarget.select() : undefined}
                    onChange={(event) => {
                      if (createOpen) {
                        setRecipientForm((current) => ({
                          ...current,
                          mobile_phone: formatMobilePhoneInput(event.target.value),
                        }));
                        return;
                      }
                      setDetailForm((current) => ({ ...current, mobile_phone: event.target.value }));
                    }}
                    disabled={basicEditOpen && inputsLocked}
                    aria-required="true"
                    required
                  />
                ) : (
                  <strong data-testid="recipient-detail-mobile-phone">
                    {formatNullable(detailViewRecipient?.mobile_phone)}
                  </strong>
                )}
              </div>

              <div className="recipient-summary-item">
                <span>본인부담금</span>
                <div className="recipient-copay-inline">
                  <select
                    className="recipient-summary-control"
                    aria-label="본인부담금"
                    data-testid={createOpen ? 'recipient-create-copay' : 'recipient-detail-copay'}
                    value={
                      createOpen || basicEditOpen
                        ? copayDraftCode
                        : normalizeCopayBenefitCode(
                            activeCopayPeriod?.benefit_code ?? detailListProjection?.benefit_code,
                          )
                    }
                    onChange={(event) =>
                      setCopayDraftCode(event.target.value as CopayBenefitCode)
                    }
                    disabled={createOpen || copaySaving || (basicEditOpen && inputsLocked)}
                  >
                    <option value="GENERAL">일반</option>
                    <option value="BASIC_LIVELIHOOD">기초</option>
                    <option value="REDUCTION_6">6%</option>
                    <option value="REDUCTION_9">9%</option>
                  </select>
                  <input
                    className="recipient-summary-control"
                    type="text"
                    aria-label="혜택 적용 시작 문구"
                    value={
                      basicEditOpen
                        ? copayDraftStartText
                        : activeCopayPeriod?.start_text ?? ''
                    }
                    onChange={(event) => setCopayDraftStartText(event.target.value)}
                    disabled={createOpen || copaySaving || (basicEditOpen && inputsLocked)}
                  />
                </div>
              </div>

              <div className="recipient-summary-item recipient-summary-item-address">
                <span>주소</span>
                {activeId || createOpen || basicEditOpen ? (
                  <div className="recipient-address-inline recipient-address-input-row">
                    <input
                      className="recipient-summary-control"
                      data-testid={createOpen ? 'recipient-postal-code-input' : 'recipient-detail-postal-code-input'}
                      aria-label="우편번호"
                      placeholder="우편번호"
                      inputMode="numeric"
                      value={createOpen ? recipientForm.postal_code : detailForm.postal_code}
                      onFocus={basicEditOpen ? (event) => event.currentTarget.select() : undefined}
                      onChange={(event) => {
                        if (createOpen) {
                          setRecipientForm((current) => ({ ...current, postal_code: event.target.value }));
                          return;
                        }
                        setDetailForm((current) => ({ ...current, postal_code: event.target.value }));
                      }}
                      disabled={basicEditOpen && inputsLocked}
                    />
                    <input
                      className="recipient-summary-control"
                      data-testid={createOpen ? 'recipient-address-input' : 'recipient-detail-address-input'}
                      aria-label="주소"
                      placeholder="주소"
                      value={createOpen ? recipientForm.address : detailForm.address}
                      onFocus={basicEditOpen ? (event) => event.currentTarget.select() : undefined}
                      onChange={(event) => {
                        if (createOpen) {
                          setRecipientForm((current) => ({ ...current, address: event.target.value }));
                          return;
                        }
                        setDetailForm((current) => ({ ...current, address: event.target.value }));
                      }}
                      disabled={basicEditOpen && inputsLocked}
                    />
                  </div>
                ) : (
                  <div className="recipient-address-inline" data-testid="recipient-detail-address">
                    <span data-testid="recipient-detail-postal-code">
                      {formatNullable(detailViewRecipient?.postal_code)}
                    </span>
                    <span data-testid="recipient-detail-address-main">
                      {formatNullable(detailViewRecipient?.address)}
                    </span>
                  </div>
                )}
              </div>

              <div className="recipient-summary-item recipient-summary-item-address">
                <span>메모</span>
                {activeId || createOpen || basicEditOpen ? (
                  <input
                    className="recipient-summary-control"
                    data-testid={createOpen ? 'recipient-memo-input' : 'recipient-detail-memo-input'}
                    value={createOpen ? recipientForm.memo : detailForm.memo}
                    onChange={(event) => {
                      if (createOpen) {
                        setRecipientForm((current) => ({ ...current, memo: event.target.value }));
                        return;
                      }
                      setDetailForm((current) => ({ ...current, memo: event.target.value }));
                    }}
                    disabled={basicEditOpen && inputsLocked}
                  />
                ) : (
                  <strong>{formatNullable(detailViewRecipient?.memo)}</strong>
                )}
              </div>
            </form>
            {createOpen && createError ? (
              <div className="recipient-inline-error" role="alert">
                {createError}
              </div>
            ) : null}
            {createOpen && createMessage ? <div className="recipient-inline-note">{createMessage}</div> : null}
            {!createOpen && detailMessage ? (
              <div className="recipient-inline-note">{detailMessage}</div>
            ) : null}
          </section>
          {detailStaleConflict ? (
            <div className="recipient-stale-panel">
              {detailError ? (
                <div
                  className="recipient-inline-error"
                  role="alert"
                  data-testid="recipient-stale-conflict-message"
                >
                  {detailError}
                </div>
              ) : null}
              <div data-testid="recipient-stale-latest-value">
                최신 서버값: {detailStaleConflict.latest.name}
              </div>
              {detailStaleConflict.sameFieldConflicts.length > 0 ? (
                <div
                  className="recipient-stale-diff"
                  data-testid="recipient-same-field-conflict-log"
                >
                  {detailStaleConflict.sameFieldConflicts.map((entry) => (
                    <div
                      key={entry.field}
                      data-testid={`recipient-conflict-field-${entry.field}`}
                    >
                      {entry.label}({entry.field}): 사용자 {entry.userValue} / 서버{' '}
                      {entry.serverValue}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="recipient-stale-diff" data-testid="recipient-stale-diff">
                  사용자 입력: {detailStaleConflict.draftAtConflict.name || '없음'} / 최신
                  서버값: {detailStaleConflict.latest.name}
                </div>
              )}
              {detailStaleConflict.canAutoReapply ? (
                <button
                  className="recipient-secondary-button"
                  data-testid="recipient-stale-reapply"
                  type="button"
                  onClick={() => void handleDetailReapply()}
                  disabled={detailSaving || detailLoading}
                >
                  최신 버전에 변경 내용 다시 적용
                </button>
              ) : null}
            </div>
          ) : null}

          <div className="recipient-payer-section">
            <span data-testid="recipient-payer-current-label">{payerCurrentLabel}</span>
            {basicEditOpen && payerGuardianSlot === 'unlisted' ? (
              <button
                className="recipient-secondary-button"
                type="button"
                data-testid="recipient-payer-self-button"
                onClick={() => setPayerGuardianSlot(null)}
                disabled={inputsLocked}
              >
                {payerSelfLabel}
              </button>
            ) : null}
          </div>
          <div className="recipient-detail-columns recipient-guardian-cards">
            {([0, 1] as GuardianSlot[]).map((guardianIndex) => {
              const form = guardianForms[guardianIndex];
              const isPayer = payerGuardianSlot === guardianIndex;
              return (
                <div className="recipient-guardian-card" key={guardianIndex}>
                  <div className="recipient-guardian-card-heading">
                    <h3 className="recipient-guardian-card-title">보호자{guardianIndex + 1} 정보</h3>
                    <label
                      className="recipient-payer-checkbox"
                      data-testid={`guardian-${guardianIndex + 1}-payer-checkbox-label`}
                    >
                      <input
                        type="checkbox"
                        data-testid={`guardian-${guardianIndex + 1}-payer-checkbox`}
                        checked={isPayer}
                        onChange={(event) =>
                          setPayerSlotExclusive(guardianIndex, event.target.checked)
                        }
                        disabled={!(createOpen || basicEditOpen) || inputsLocked}
                      />
                      납부자
                    </label>
                  </div>
                  <section
                    className={`recipient-subsection recipient-guardian-section${createOpen || basicEditOpen ? ' is-editing' : ''}`}
                    data-testid={`recipient-guardian-${guardianIndex + 1}-section`}
                  >
                    <div
                      id={`guardian-${guardianIndex + 1}-form`}
                      className="recipient-subform recipient-guardian-form"
                    >
                      <label className="recipient-field">
                        이름
                        <input
                          data-testid={`guardian-${guardianIndex + 1}-name-input`}
                          value={form.name}
                          onChange={(event) =>
                            setGuardianForms((current) => {
                              const next: GuardianFormSlots = [current[0], current[1]];
                              next[guardianIndex] = { ...next[guardianIndex], name: event.target.value };
                              return next;
                            })
                          }
                          disabled={!(createOpen || basicEditOpen) || inputsLocked}
                        />
                      </label>
                      <label className="recipient-field">
                        관계
                        <input
                          data-testid={`guardian-${guardianIndex + 1}-relationship-input`}
                          value={form.relationship_text}
                          onChange={(event) =>
                            setGuardianForms((current) => {
                              const next: GuardianFormSlots = [current[0], current[1]];
                              next[guardianIndex] = {
                                ...next[guardianIndex],
                                relationship_text: event.target.value,
                              };
                              return next;
                            })
                          }
                          disabled={!(createOpen || basicEditOpen) || inputsLocked}
                        />
                      </label>
                      <label className="recipient-field">
                        전화번호
                        <input
                          data-testid={`guardian-${guardianIndex + 1}-phone-input`}
                          value={form.phone}
                          onChange={(event) =>
                            setGuardianForms((current) => {
                              const next: GuardianFormSlots = [current[0], current[1]];
                              next[guardianIndex] = { ...next[guardianIndex], phone: event.target.value };
                              return next;
                            })
                          }
                          disabled={!(createOpen || basicEditOpen) || inputsLocked}
                        />
                      </label>
                      <label className="recipient-field">
                        이메일
                        <input
                          data-testid={`guardian-${guardianIndex + 1}-email-input`}
                          type="email"
                          value={form.email}
                          onChange={(event) =>
                            setGuardianForms((current) => {
                              const next: GuardianFormSlots = [current[0], current[1]];
                              next[guardianIndex] = { ...next[guardianIndex], email: event.target.value };
                              return next;
                            })
                          }
                          disabled={!(createOpen || basicEditOpen) || inputsLocked}
                        />
                      </label>
                      <label className="recipient-field recipient-field-wide">
                        주소
                        <input
                          data-testid={`guardian-${guardianIndex + 1}-address-input`}
                          value={form.address}
                          onChange={(event) =>
                            setGuardianForms((current) => {
                              const next: GuardianFormSlots = [current[0], current[1]];
                              next[guardianIndex] = {
                                ...next[guardianIndex],
                                address: event.target.value,
                              };
                              return next;
                            })
                          }
                          disabled={!(createOpen || basicEditOpen) || inputsLocked}
                        />
                      </label>
                      {guardianError ? <div className="recipient-inline-error">{guardianError}</div> : null}
                      {guardianMessage ? <div className="recipient-inline-note">{guardianMessage}</div> : null}
                    </div>
                  </section>
                </div>
              );
            })}
          </div>

            </>
          ) : null}

          {detailExtrasOpen ? (
            <div className="recipient-detail-extra-sections" data-testid="recipient-detail-extra-sections">
              {detailBatchEditing ? (
                <div className="recipient-detail-batch-toolbar" data-testid="recipient-detail-batch-toolbar">
                  <strong>상세 수정</strong>
                  <div>
                    <button
                      className="recipient-secondary-button"
                      type="button"
                      onClick={() => void handleDetailBatchSave()}
                      disabled={detailBatchSaving}
                    >
                      {detailBatchSaving ? '저장 중…' : '저장'}
                    </button>
                    <button
                      className="recipient-secondary-button"
                      type="button"
                      onClick={cancelDetailBatchEdit}
                      disabled={detailBatchSaving}
                    >
                      취소
                    </button>
                  </div>
                </div>
              ) : null}
              {activeId ? (
                <RecipientW1cPanel
                  key={`w1c-${activeId}-${detailBatchRevision}`}
                  recipientId={activeId}
                />
              ) : null}
              {activeId ? (
                <RecipientServicePlanNoticePanel
                  key={`service-plan-${activeId}-${detailBatchRevision}`}
                  recipientId={activeId}
                />
              ) : null}
              {activeId ? (
                <RecipientContractPanel
                  key={`contract-${activeId}-${detailBatchRevision}`}
                  recipientId={activeId}
                  recipientNo={detailViewRecipient?.recipient_no ?? null}
                  onRecipientMutated={() => {
                    setListReload((current) => current + 1);
                    setWorkspaceReload((current) => current + 1);
                  }}
                />
              ) : null}
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
};

export default RecipientsPage;
