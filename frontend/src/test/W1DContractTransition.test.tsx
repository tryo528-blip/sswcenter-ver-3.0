import './setup';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import RecipientsPage from '../pages/RecipientsPage';

const syntheticRecipient = {
  id: 42,
  name: 'TEST_W1D_RECIPIENT',
  birth_date: '1950-01-01',
  sex_code: 'FEMALE',
  recipient_status: 'ACTIVE',
  postal_code: null,
  address: null,
  home_phone: null,
  mobile_phone: null,
  recipient_no: null,
  row_version: 1,
};

const contractNoSelectors = [
  'input[name="contract_no"]',
  'select[name="contract_no"]',
  'textarea[name="contract_no"]',
  '[data-testid="contract-no-input"]',
].join(', ');

const signerFkSelectors = [
  'select[name="signer_guardian_id"]',
  'select[name="signer_payer_id"]',
  '[data-testid="signer-guardian-select"]',
  '[data-testid="signer-payer-select"]',
].join(', ');

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('W1D RED: contract and certification transition UI', () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>;
  let lastContractPost: Record<string, unknown> | null;
  let lastTransitionPreview: Record<string, unknown> | null;
  let lastTransitionApply: Record<string, unknown> | null;
  let transitionApplyCalls: number;
  let deferredApplyResponse: Promise<Response> | null;

  beforeEach(() => {
    lastContractPost = null;
    lastTransitionPreview = null;
    lastTransitionApply = null;
    transitionApplyCalls = 0;
    deferredApplyResponse = null;
    fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      const base = '/api/v1/recipients/42';

      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse({ items: [syntheticRecipient], total: 1, page: 1, page_size: 100 });
      }
      if (url.pathname === base && method === 'GET') {
        return jsonResponse(syntheticRecipient);
      }
      if (url.pathname === `${base}/contracts` && method === 'GET') {
        return jsonResponse({ items: [] });
      }
      if (url.pathname === `${base}/contracts` && method === 'POST') {
        lastContractPost = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
        return jsonResponse(
          {
            id: 1,
            recipient_id: 42,
            service_type_code: lastContractPost.service_type_code,
            start_date: lastContractPost.start_date,
            end_date: lastContractPost.end_date ?? null,
            service_start_date: lastContractPost.service_start_date ?? null,
            signer_name: lastContractPost.signer_name ?? null,
            signer_relationship_text: lastContractPost.signer_relationship_text ?? null,
            signer_phone: lastContractPost.signer_phone ?? null,
            end_reason_text: lastContractPost.end_reason_text ?? null,
            row_version: 1,
          },
          201,
        );
      }
      if (url.pathname === `${base}/certification-transitions/preview` && method === 'POST') {
        lastTransitionPreview = JSON.parse(String(init?.body ?? '{}')) as Record<
          string,
          unknown
        >;
        return jsonResponse({
          preview_token: 'TEST_W1D_PREVIEW_TOKEN',
          canonical_hash: 'abc',
          serialization_version: 'w1d-transition-v1',
          proposed_end_date: '2026-06-30',
          affected_certification_period_ids: [1],
          affected_grade_period_ids: [1],
          affected_contract_ids: [1],
          service_multiset: ['HOME_CARE'],
          replacement_preview: [{ service_type_code: 'HOME_CARE', start_date: '2026-07-01' }],
        });
      }
      if (url.pathname === `${base}/certification-transitions/apply` && method === 'POST') {
        transitionApplyCalls += 1;
        lastTransitionApply = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
        if (deferredApplyResponse) return deferredApplyResponse;
        if (lastTransitionApply.confirmed !== true) {
          // R4-06: top-level ErrorEnvelope (field_errors/details not nested under error).
          return jsonResponse(
            {
              error: {
                code: 'CERTIFICATION_TRANSITION_CONFIRMATION_REQUIRED',
                message: '확인이 필요합니다.',
              },
              field_errors: [],
              details: {},
              request_id: '00000000-0000-4000-8000-000000000001',
            },
            422,
          );
        }
        return jsonResponse({
          recipient_id: 42,
          ended_certification_period_ids: [1],
          ended_grade_period_ids: [1],
          ended_contract_ids: [1],
          new_certification_period_id: 2,
          new_grade_period_id: 2,
          new_contract_ids: [2],
          audit_correlation_id: '00000000-0000-4000-8000-000000000042',
          recipient_no: 'R0000000001',
        });
      }
      // Nested W1B/W1C lists empty so detail can open.
      if (
        method === 'GET' &&
        [
          `${base}/guardians`,
          `${base}/primary-guardian-periods`,
          `${base}/payer-snapshots`,
          `${base}/certification-identity`,
          `${base}/certification-periods`,
          `${base}/grade-periods`,
          `${base}/benefit-periods`,
          `${base}/approval-amount-periods`,
        ].some((path) => url.pathname === path || url.pathname.startsWith(path))
      ) {
        if (url.pathname.endsWith('certification-identity')) {
          return jsonResponse(
            {
              error: {
                code: 'CERTIFICATION_IDENTITY_NOT_FOUND',
                message: '없음',
              },
              field_errors: [],
              details: {},
              request_id: '00000000-0000-4000-8000-000000000002',
            },
            404,
          );
        }
        return jsonResponse({ items: [] });
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  async function openRecipientDetail() {
    render(<RecipientsPage />);
    await waitFor(() => {
      expect(
        fetchSpy.mock.calls.some(([input]) => String(input).includes('/api/v1/recipients')),
        'W1D_UI_RECIPIENT_LIST_MISSING',
      ).toBe(true);
    });
    const row = await screen.findByTestId('recipient-name-option');
    fireEvent.click(row);
    await waitFor(() => {
      expect(
        screen.queryByTestId('recipient-detail-workspace'),
        'W1D_UI_RECIPIENT_DETAIL_MISSING',
      ).toBeTruthy();
    });
    // Confirmed UX: initial basic detail shows recipient + guardian 1/2 only.
    // Contract / certification-transition panels stay collapsed until the toggle.
    // Require the real basic-information form control (not recipient-no display).
    const nameInput = await screen.findByTestId('recipient-detail-name-input');
    expect(nameInput, 'W1D_UI_RECIPIENT_BASIC_INFO_MISSING').toBeInTheDocument();
    expect(
      (nameInput as HTMLInputElement).value,
      'W1D_UI_RECIPIENT_BASIC_INFO_VALUE_MISMATCH',
    ).toBe(syntheticRecipient.name);
    expect(
      screen.getByTestId('recipient-guardian-1-section'),
      'W1D_UI_GUARDIAN_1_SECTION_MISSING',
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('recipient-guardian-2-section'),
      'W1D_UI_GUARDIAN_2_SECTION_MISSING',
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId('recipient-contract-panel'),
      'W1D_UI_CONTRACT_PANEL_VISIBLE_BEFORE_TOGGLE',
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId('certification-transition-panel'),
      'W1D_UI_TRANSITION_PANEL_VISIBLE_BEFORE_TOGGLE',
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId('recipient-detail-extra-sections'),
      'W1D_UI_EXTRA_SECTIONS_VISIBLE_BEFORE_TOGGLE',
    ).not.toBeInTheDocument();
  }

  /**
   * Expand collapsed extra panels via the accessible detail toggle control
   * (closed name: 상세; open name: 기본정보; data-testid: recipient-detail-toggle).
   * Role/name/state are primary; testid is secondary identity only.
   * Contract and certification-transition panels mount only after this click.
   */
  async function expandDetailExtras() {
    const toggle = screen.getByRole('button', { name: '상세' });
    expect(toggle, 'W1D_UI_DETAIL_EXTRAS_TOGGLE_MISSING').toBeInTheDocument();
    // Secondary identity only — not a substitute for role/name selection.
    expect(toggle).toHaveAttribute('data-testid', 'recipient-detail-toggle');
    expect(
      toggle.getAttribute('aria-expanded'),
      'W1D_UI_DETAIL_EXTRAS_ALREADY_EXPANDED',
    ).toBe('false');
    fireEvent.click(toggle);
    const expandedToggle = screen.getByRole('button', { name: '기본정보' });
    expect(
      expandedToggle.getAttribute('aria-expanded'),
      'W1D_UI_DETAIL_EXTRAS_NOT_EXPANDED_AFTER_CLICK',
    ).toBe('true');
    // Unique container first, then required panels separately (no multi-node OR).
    await waitFor(() => {
      expect(
        screen.getByTestId('recipient-detail-extra-sections'),
        'W1D_UI_EXTRA_PANELS_NOT_REVEALED_AFTER_TOGGLE_EXTRAS',
      ).toBeInTheDocument();
    });
    expect(
      screen.getByTestId('recipient-contract-panel'),
      'W1D_UI_EXTRA_PANELS_NOT_REVEALED_AFTER_TOGGLE_CONTRACT',
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('certification-transition-panel'),
      'W1D_UI_EXTRA_PANELS_NOT_REVEALED_AFTER_TOGGLE_TRANSITION',
    ).toBeInTheDocument();
  }

  function fillRequiredTransitionFields(transition: HTMLElement) {
    fireEvent.change(within(transition).getByTestId('transition-new-start-date'), {
      target: { value: '2026-07-01' },
    });
    fireEvent.change(within(transition).getByTestId('transition-new-end-date'), {
      target: { value: '2027-06-30' },
    });
    fireEvent.change(within(transition).getByTestId('transition-new-grade-code'), {
      target: { value: '4' },
    });
    fireEvent.change(within(transition).getByTestId('transition-new-grade-start-date'), {
      target: { value: '2026-07-01' },
    });
    fireEvent.change(within(transition).getByTestId('transition-new-grade-end-date'), {
      target: { value: '2027-06-30' },
    });
  }

  test('exposes contract panel without contract_no or forced signer FK', async () => {
    await openRecipientDetail();
    await expandDetailExtras();

    const panel = screen.queryByTestId('recipient-contract-panel');
    expect(panel, 'W1D_UI_CONTRACT_PANEL_MISSING').toBeInTheDocument();
    if (!panel) return;

    const form = within(panel).queryByTestId('contract-create-form');
    expect(form, 'W1D_UI_CONTRACT_CREATE_FORM_MISSING').toBeInTheDocument();
    if (!form) return;

    expect(form.querySelectorAll(contractNoSelectors).length, 'W1D_ABS08_UI_CONTRACT_NO_INPUT').toBe(
      0,
    );
    expect(form.querySelectorAll(signerFkSelectors).length, 'W1D_SIG01_UI_SIGNER_FK_FORCED').toBe(0);

    const serviceType = within(form).queryByTestId('contract-service-type-select');
    const startDate = within(form).queryByTestId('contract-start-date-input');
    const endDate = within(form).queryByTestId('contract-end-date-input');
    const serviceStart = within(form).queryByTestId('contract-service-start-date-input');
    const endReason = within(form).queryByTestId('contract-end-reason-input');
    const signerName = within(form).queryByTestId('contract-signer-name-input');

    expect(serviceType, 'W1D_CON01_UI_SERVICE_TYPE_MISSING').toBeInTheDocument();
    expect(startDate, 'W1D_CON01_UI_START_DATE_MISSING').toBeInTheDocument();
    expect(endDate, 'W1D_CON01_UI_END_DATE_MISSING').toBeInTheDocument();
    expect(serviceStart, 'W1D_CON01_UI_SERVICE_START_MISSING').toBeInTheDocument();
    expect(endReason, 'W1D_CON02_UI_END_REASON_MISSING').toBeInTheDocument();
    expect(signerName, 'W1D_SIG01_UI_SIGNER_NAME_MISSING').toBeInTheDocument();

    if (serviceType) {
      expect(
        serviceType.matches(':required') || serviceType.getAttribute('aria-required') === 'true',
        'W1D_CON01_UI_SERVICE_TYPE_NOT_REQUIRED',
      ).toBe(true);
    }
    if (startDate) {
      expect(
        startDate.matches(':required') || startDate.getAttribute('aria-required') === 'true',
        'W1D_CON01_UI_START_DATE_NOT_REQUIRED',
      ).toBe(true);
    }
    if (serviceStart) {
      expect(
        serviceStart.matches(':required') || serviceStart.getAttribute('aria-required') === 'true',
        'W1D_ABS10_UI_SERVICE_START_REQUIRED',
      ).toBe(false);
    }
    if (endReason) {
      expect((endReason as HTMLInputElement).value, 'W1D_CON02_UI_END_REASON_DEFAULT_NOT_EMPTY').toBe(
        '',
      );
      expect((endReason as HTMLInputElement).value, 'W1D_ABS09_UI_DEATH_DEFAULT').not.toBe('사망');
    }

    const reactivate = within(panel).queryByTestId('contract-reactivate-button');
    expect(reactivate, 'W1D_CON03_UI_REACTIVATE_BUTTON_FORBIDDEN').toBeNull();
    expect(
      within(panel).queryByTestId('contract-new-button') ||
        within(panel).queryByRole('button', { name: /새 계약/ }),
      'W1D_CON03_UI_NEW_CONTRACT_FLOW_MISSING',
    ).toBeTruthy();
  });

  test('submits minimal contract without contract_no and optional blanks', async () => {
    let lastDetailBatch: Record<string, unknown> | null = null;
    fetchSpy.mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      const base = '/api/v1/recipients/42';

      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse({ items: [syntheticRecipient], total: 1, page: 1, page_size: 100 });
      }
      if (url.pathname === base && method === 'GET') {
        return jsonResponse(syntheticRecipient);
      }
      if (url.pathname === `${base}/contracts` && method === 'GET') {
        return jsonResponse({ items: [] });
      }
      if (url.pathname === `${base}/detail-batch` && method === 'POST') {
        lastDetailBatch = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
        return jsonResponse({
          recipient_id: 42,
          saved_sections: ['contract'],
        });
      }
      if (
        method === 'GET' &&
        [
          `${base}/guardians`,
          `${base}/primary-guardian-periods`,
          `${base}/payer-snapshots`,
          `${base}/certification-identity`,
          `${base}/certification-periods`,
          `${base}/grade-periods`,
          `${base}/benefit-periods`,
          `${base}/approval-amount-periods`,
        ].some((path) => url.pathname === path || url.pathname.startsWith(path))
      ) {
        if (url.pathname.endsWith('certification-identity')) {
          return jsonResponse(
            {
              error: {
                code: 'CERTIFICATION_IDENTITY_NOT_FOUND',
                message: '없음',
              },
              field_errors: [],
              details: {},
              request_id: '00000000-0000-4000-8000-000000000002',
            },
            404,
          );
        }
        return jsonResponse({ items: [] });
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    });

    await openRecipientDetail();
    await expandDetailExtras();
    // Detail extras use batch-managed editing: enter 수정, then batch 저장.
    fireEvent.click(screen.getByTestId('recipient-basic-edit'));
    await waitFor(() => {
      expect(screen.getByTestId('recipient-detail-batch-toolbar')).toBeInTheDocument();
    });

    const form = screen.queryByTestId('contract-create-form');
    expect(form, 'W1D_UI_CONTRACT_CREATE_FORM_MISSING').toBeInTheDocument();
    if (!form) return;

    const serviceType = within(form).getByTestId('contract-service-type-select');
    const startDate = within(form).getByTestId('contract-start-date-input');
    fireEvent.change(serviceType, { target: { value: 'HOME_CARE' } });
    fireEvent.change(startDate, { target: { value: '2026-07-01' } });
    // Native form submit is intercepted; contract is collected by detail-batch save.
    fireEvent.click(within(screen.getByTestId('recipient-detail-batch-toolbar')).getByRole('button', { name: '저장' }));

    await waitFor(() => {
      expect(lastDetailBatch, 'W1D_UI_CONTRACT_POST_MISSING').not.toBeNull();
    });
    expect(lastDetailBatch, 'W1D_UI_CONTRACT_POST_MISSING').not.toBeNull();
    if (!lastDetailBatch) return;
    const contract = lastDetailBatch.contract as Record<string, unknown> | undefined;
    expect(contract, 'W1D_UI_CONTRACT_POST_MISSING').toBeTruthy();
    if (!contract) return;
    expect(
      Object.prototype.hasOwnProperty.call(contract, 'contract_no'),
      'W1D_ABS08_UI_POST_CONTRACT_NO_KEY',
    ).toBe(false);
    expect(contract.service_type_code, 'W1D_CON01_UI_POST_SERVICE_DRIFT').toBe('HOME_CARE');
    expect(contract.start_date, 'W1D_CON01_UI_POST_START_DRIFT').toBe('2026-07-01');
  });

  test('transition preview gates apply until explicit confirmation', async () => {
    await openRecipientDetail();
    await expandDetailExtras();

    const transition = screen.queryByTestId('certification-transition-panel');
    expect(transition, 'W1D_UI_TRANSITION_PANEL_MISSING').toBeInTheDocument();
    if (!transition) return;

    const applyButton = within(transition).queryByTestId('transition-apply-button');
    expect(applyButton, 'W1D_TRN01_UI_APPLY_BUTTON_MISSING').toBeInTheDocument();
    if (!applyButton) return;
    expect(
      (applyButton as HTMLButtonElement).disabled,
      'W1D_TRN01_UI_APPLY_ENABLED_BEFORE_CONFIRM',
    ).toBe(true);

    // R12-03: sealed transition input controls (exact five testids).
    for (const tid of [
      'transition-new-start-date',
      'transition-new-end-date',
      'transition-new-grade-code',
      'transition-new-grade-start-date',
      'transition-new-grade-end-date',
    ] as const) {
      expect(
        within(transition).queryByTestId(tid),
        `W1D_TRN01_UI_CONTROL_MISSING_${tid}`,
      ).toBeInTheDocument();
    }
    const previewButton = within(transition).queryByTestId('transition-preview-button');
    expect(previewButton, 'W1D_TRN01_UI_PREVIEW_BUTTON_MISSING').toBeInTheDocument();
    expect(
      (previewButton as HTMLButtonElement).disabled,
      'W1D_TRN01_UI_PREVIEW_ENABLED_WITH_BLANK_REQUIRED_FIELDS',
    ).toBe(true);
    for (const tid of [
      'transition-new-start-date',
      'transition-new-end-date',
      'transition-new-grade-code',
      'transition-new-grade-start-date',
      'transition-new-grade-end-date',
    ] as const) {
      expect(within(transition).getByTestId(tid)).toHaveAttribute('aria-required', 'true');
    }
    fillRequiredTransitionFields(transition);
    expect((previewButton as HTMLButtonElement).disabled).toBe(false);
    if (previewButton) {
      fireEvent.click(previewButton);
    }

    await waitFor(() => {
      expect(
        within(transition).queryByTestId('transition-impact-list'),
        'W1D_TRN01_UI_IMPACT_LIST_MISSING',
      ).toBeInTheDocument();
    });
    expect(lastTransitionPreview).toMatchObject({
      new_start_date: '2026-07-01',
      new_end_date: '2027-06-30',
      new_grade_code: '4',
      new_grade_start_date: '2026-07-01',
      new_grade_end_date: '2027-06-30',
    });
    expect(
      within(transition).queryByTestId('transition-affected-certification-ids'),
    ).toHaveTextContent('1');
    expect(within(transition).queryByTestId('transition-affected-grade-ids')).toHaveTextContent(
      '1',
    );
    expect(
      within(transition).queryByTestId('transition-affected-contract-ids'),
    ).toHaveTextContent('1');
    expect(
      within(transition).queryByTestId('transition-service-multiset'),
      'W1D_TRN01_UI_SERVICE_MULTISET_MISSING',
    ).toBeInTheDocument();
    expect(
      within(transition).queryByTestId('transition-proposed-end-date'),
      'W1D_TRN01_UI_PROPOSED_END_MISSING',
    ).toBeInTheDocument();

    const confirm = within(transition).queryByTestId('transition-confirm-checkbox');
    expect(confirm, 'W1D_TRN01_UI_CONFIRM_CHECKBOX_MISSING').toBeInTheDocument();
    if (!confirm) return;
    fireEvent.click(confirm);

    expect(
      (applyButton as HTMLButtonElement).disabled,
      'W1D_TRN01_UI_APPLY_STILL_DISABLED_AFTER_CONFIRM',
    ).toBe(false);

    // Stale path discards preview + confirmation.
    // Simulate stale by dispatching a custom event if the panel listens; otherwise require banner testid after mock 409.
    fireEvent.click(applyButton);
    await waitFor(() => {
      expect(
        within(transition).queryByTestId('transition-partial-success'),
        'W1D_TRN04_UI_PARTIAL_SUCCESS_BANNER_FORBIDDEN',
      ).toBeNull();
    });
  });

  test('stale 409 discards preview confirmation and disables apply', async () => {
    // J-M04: dedicated STALE path — unconditional UI invalidation assertions.
    fetchSpy.mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      const base = '/api/v1/recipients/42';
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse({ items: [syntheticRecipient], total: 1, page: 1, page_size: 100 });
      }
      if (url.pathname === base && method === 'GET') {
        return jsonResponse(syntheticRecipient);
      }
      if (method === 'GET' && url.pathname.startsWith(base)) {
        if (url.pathname.endsWith('certification-identity')) {
          return jsonResponse(
            {
              error: { code: 'CERTIFICATION_IDENTITY_NOT_FOUND', message: '없음' },
              field_errors: [],
              details: {},
              request_id: '00000000-0000-4000-8000-000000000099',
            },
            404,
          );
        }
        return jsonResponse({ items: [] });
      }
      if (url.pathname === `${base}/certification-transitions/preview` && method === 'POST') {
        return jsonResponse({
          preview_token: 'TEST_W1D_PREVIEW_TOKEN',
          canonical_hash: 'abc',
          serialization_version: 'w1d-transition-v1',
          proposed_end_date: '2026-06-30',
          affected_certification_period_ids: [1],
          affected_grade_period_ids: [1],
          affected_contract_ids: [1],
          service_multiset: ['HOME_CARE'],
          replacement_preview: [],
        });
      }
      if (url.pathname === `${base}/certification-transitions/apply` && method === 'POST') {
        return jsonResponse(
          {
            error: {
              code: 'CERTIFICATION_TRANSITION_STALE',
              message: '다시 미리보기',
            },
            field_errors: [],
            details: {},
            request_id: '00000000-0000-4000-8000-000000000001',
          },
          409,
        );
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    });

    await openRecipientDetail();
    await expandDetailExtras();
    const transition = screen.queryByTestId('certification-transition-panel');
    expect(transition, 'W1D_UI_TRANSITION_PANEL_MISSING').toBeInTheDocument();
    if (!transition) return;
    const previewButton = within(transition).queryByTestId('transition-preview-button');
    expect(previewButton, 'W1D_TRN01_UI_PREVIEW_BUTTON_MISSING').toBeInTheDocument();
    fillRequiredTransitionFields(transition);
    if (previewButton) fireEvent.click(previewButton);
    await waitFor(() => {
      expect(
        within(transition).queryByTestId('transition-impact-list'),
        'W1D_TRN01_UI_IMPACT_LIST_MISSING',
      ).toBeInTheDocument();
    });
    const confirm = within(transition).queryByTestId('transition-confirm-checkbox');
    expect(confirm, 'W1D_TRN01_UI_CONFIRM_CHECKBOX_MISSING').toBeInTheDocument();
    if (confirm) fireEvent.click(confirm);
    const applyButton = within(transition).queryByTestId('transition-apply-button');
    expect(applyButton, 'W1D_TRN01_UI_APPLY_BUTTON_MISSING').toBeInTheDocument();
    if (applyButton) fireEvent.click(applyButton);

    await waitFor(() => {
      const staleBanner = within(transition).queryByTestId('transition-stale-banner');
      expect(
        staleBanner,
        'W1D_TRN03_UI_STALE_BANNER_MISSING',
      ).toBeInTheDocument();
      expect(staleBanner).toHaveAttribute('role', 'alert');
      expect(staleBanner).toHaveAttribute('aria-live', 'assertive');
    });
    expect(
      within(transition).getByText(/다시 미리보기|미리보기/),
      'W1D_TRN03_UI_REPREVIEW_GUIDANCE_MISSING',
    ).toBeInTheDocument();
    expect(confirm, 'W1D_TRN03_UI_CONFIRM_NOT_CLEARED_ON_STALE').not.toBeChecked();
    expect(
      (applyButton as HTMLButtonElement).disabled,
      'W1D_TRN03_UI_APPLY_NOT_DISABLED_ON_STALE',
    ).toBe(true);
    expect(
      within(transition).queryByTestId('transition-impact-list'),
      'W1D_TRN03_UI_PREVIEW_NOT_DISCARDED',
    ).toBeNull();
  });

  test('rapid apply double click sends exactly one request while applying', async () => {
    let resolveApply!: (response: Response) => void;
    deferredApplyResponse = new Promise<Response>((resolve) => {
      resolveApply = resolve;
    });

    await openRecipientDetail();
    await expandDetailExtras();
    const transition = screen.getByTestId('certification-transition-panel');
    fillRequiredTransitionFields(transition);
    fireEvent.click(within(transition).getByTestId('transition-preview-button'));
    await waitFor(() => {
      expect(within(transition).queryByTestId('transition-impact-list')).toBeInTheDocument();
    });
    fireEvent.click(within(transition).getByTestId('transition-confirm-checkbox'));

    const applyButton = within(transition).getByTestId(
      'transition-apply-button',
    ) as HTMLButtonElement;
    fireEvent.click(applyButton);
    fireEvent.click(applyButton);

    expect(transitionApplyCalls).toBe(1);
    expect(applyButton).toBeDisabled();
    expect(applyButton).toHaveTextContent('적용 중');

    resolveApply(
      jsonResponse({
        recipient_id: 42,
        ended_certification_period_ids: [1],
        ended_grade_period_ids: [1],
        ended_contract_ids: [1],
        new_certification_period_id: 2,
        new_grade_period_id: 2,
        new_contract_ids: [2],
        audit_correlation_id: '00000000-0000-4000-8000-000000000042',
        recipient_no: 'R0000000001',
      }),
    );
    await waitFor(() => expect(applyButton).toHaveTextContent('전환 적용'));
    expect(transitionApplyCalls).toBe(1);
  });

  test('recipient_no remains non-editable before first contract', async () => {
    await openRecipientDetail();
    const detail = screen.queryByTestId('recipient-detail-workspace') ?? document.body;
    expect(
      detail.querySelectorAll(
        'input[name="recipient_no"], [data-testid="recipient-no-input"]',
      ).length,
      'W1D_REC03_UI_RECIPIENT_NO_EDITABLE',
    ).toBe(0);
    // 미부여 display may already exist from W1B; do not require contract panel for this assert alone.
  });
});
