import './setup';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import RecipientW1cPanel from '../components/recipients/RecipientW1cPanel';

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const rawJsonResponse = (body: string, status = 200) =>
  new Response(body, {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

describe('W1C recipient certification ledgers', () => {
  let identity: Record<string, unknown> | null;
  let benefitRows: Array<Record<string, unknown>>;
  let approvalListJson: string;
  let postedIdentity: Record<string, unknown> | null;
  let postedBenefit: Record<string, unknown> | null;
  let postedApprovalBody: string | null;

  beforeEach(() => {
    identity = null;
    benefitRows = [];
    approvalListJson = '{"items":[]}';
    postedIdentity = null;
    postedBenefit = null;
    postedApprovalBody = null;

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      const base = '/api/v1/recipients/42';

      if (url.pathname === `${base}/certification-identity` && method === 'GET') {
        return identity
          ? jsonResponse(identity)
          : jsonResponse(
              {
                error: {
                  code: 'CERTIFICATION_IDENTITY_NOT_FOUND',
                  message: '인정 본번호가 등록되지 않았습니다.',
                  field_errors: [],
                  details: {},
                },
              },
              404,
            );
      }
      if (url.pathname === `${base}/certification-identity` && method === 'POST') {
        postedIdentity = JSON.parse(String(init?.body)) as Record<string, unknown>;
        identity = {
          recipient_id: 42,
          certification_number: 'L1234567890',
          row_version: 1,
        };
        return jsonResponse(identity, 201);
      }
      if (url.pathname === `${base}/certification-periods`) {
        return method === 'GET'
          ? jsonResponse({ items: [] })
          : jsonResponse({}, 201);
      }
      if (url.pathname === `${base}/grade-periods`) {
        return method === 'GET'
          ? jsonResponse({ items: [] })
          : jsonResponse({}, 201);
      }
      if (url.pathname === `${base}/benefit-periods` && method === 'GET') {
        return jsonResponse({ items: benefitRows });
      }
      if (url.pathname === `${base}/benefit-periods` && method === 'POST') {
        postedBenefit = JSON.parse(String(init?.body)) as Record<string, unknown>;
        const created = {
          id: 1,
          recipient_id: 42,
          ...postedBenefit,
          invalidated_at_utc: null,
          replacement_benefit_period_id: null,
          row_version: 1,
        };
        benefitRows = [created];
        return jsonResponse(created, 201);
      }
      if (url.pathname === `${base}/approval-amount-periods`) {
        if (method === 'GET') return rawJsonResponse(approvalListJson);
        postedApprovalBody = String(init?.body);
        const amountMatch = postedApprovalBody.match(/"amount_krw":([0-9]+)/);
        if (!amountMatch) return jsonResponse({}, 422);
        const parsedBody = JSON.parse(
          postedApprovalBody.replace(
            /"amount_krw":[0-9]+/,
            `"amount_krw":"${amountMatch[1]}"`,
          ),
        ) as Record<string, unknown>;
        const createdJson = JSON.stringify({
          id: 9,
          recipient_id: 42,
          ...parsedBody,
          amount_krw: null,
          invalidated_at_utc: null,
          replacement_local_approval_amount_period_id: null,
          row_version: 1,
        }).replace('"amount_krw":null', `"amount_krw":${amountMatch[1]}`);
        approvalListJson = `{"items":[${createdJson}]}`;
        return rawJsonResponse(createdJson, 201);
      }
      return jsonResponse({ error: { code: 'NOT_FOUND', message: 'not found' } }, 404);
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  test('shows canonical preview and submits the original accepted certification input', async () => {
    render(<RecipientW1cPanel recipientId={42} />);

    await waitFor(() => {
      expect(screen.getByTestId('w1c-panel')).toBeInTheDocument();
      expect(screen.getByTestId('w1c-certification-input')).toBeEnabled();
    });

    fireEvent.change(screen.getByTestId('w1c-certification-input'), {
      target: { value: ' l1234567890-100 ' },
    });
    expect(screen.getByTestId('w1c-certification-preview')).toHaveTextContent(
      'L1234567890',
    );
    fireEvent.click(screen.getByRole('button', { name: '인정 본번호 등록' }));

    await waitFor(() => {
      expect(postedIdentity).toEqual({
        certification_number: ' l1234567890-100 ',
      });
      expect(screen.getByText('L1234567890')).toBeInTheDocument();
    });
  });

  test('exposes only exact grade and benefit choices without an implicit GENERAL value', async () => {
    render(<RecipientW1cPanel recipientId={42} />);

    await waitFor(() => {
      expect(screen.getByTestId('w1c-benefit-select')).toBeEnabled();
    });

    const gradeValues = Array.from(
      screen.getByTestId('w1c-grade-select').querySelectorAll('option'),
    ).map((option) => option.value);
    expect(gradeValues).toEqual(['1', '2', '3', '4', '5']);

    const benefitSelect = screen.getByTestId(
      'w1c-benefit-select',
    ) as HTMLSelectElement;
    const benefitValues = Array.from(benefitSelect.querySelectorAll('option')).map(
      (option) => option.value,
    );
    expect(benefitValues).toEqual([
      '',
      'GENERAL',
      'BASIC_LIVELIHOOD',
      'REDUCTION_6',
      'REDUCTION_9',
      'MEDICAL_6',
      'MEDICAL_9',
    ]);
    expect(benefitSelect.value).toBe('');
    expect(screen.getByTestId('w1c-benefit-empty')).toHaveTextContent(
      '적용 혜택 자료가 없습니다.',
    );
    expect(screen.queryByRole('button', { name: /GENERAL|일반.*자동/ })).toBeNull();
  });

  test('creates a selected benefit period without a rate or automatic fallback field', async () => {
    render(<RecipientW1cPanel recipientId={42} />);

    await waitFor(() => {
      expect(screen.getByTestId('w1c-benefit-select')).toBeEnabled();
    });
    fireEvent.change(screen.getByTestId('w1c-benefit-select'), {
      target: { value: 'MEDICAL_9' },
    });
    fireEvent.change(screen.getByTestId('w1c-benefit-start-date'), {
      target: { value: '2026-07-15' },
    });
    fireEvent.click(screen.getByRole('button', { name: '혜택기간 등록' }));

    await waitFor(() => {
      expect(postedBenefit).toEqual({
        benefit_code: 'MEDICAL_9',
        start_date: '2026-07-15',
        end_date: null,
      });
    });
    expect(postedBenefit).not.toHaveProperty('rate');
    expect(postedBenefit).not.toHaveProperty('benefit_rate');
  });

  test('preserves PostgreSQL bigint maximum through GET, POST, and UI rendering', async () => {
    approvalListJson =
      '{"items":[{"id":8,"recipient_id":42,"amount_krw":9223372036854775807,' +
      '"start_date":"2026-07-01","end_date":null,"invalidated_at_utc":null,' +
      '"replacement_local_approval_amount_period_id":null,"row_version":1}]}';
    render(<RecipientW1cPanel recipientId={42} />);

    await waitFor(() => {
      expect(
        screen.getByText('9,223,372,036,854,775,807원'),
      ).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId('w1c-approval-amount-input'), {
      target: { value: '9223372036854775807' },
    });
    fireEvent.change(screen.getByTestId('w1c-approval-start-date'), {
      target: { value: '2026-08-01' },
    });
    fireEvent.click(screen.getByRole('button', { name: '승인금액 기간 등록' }));

    await waitFor(() => {
      expect(postedApprovalBody).toContain(
        '"amount_krw":9223372036854775807',
      );
      expect(postedApprovalBody).not.toContain(
        '"amount_krw":"9223372036854775807"',
      );
      expect(
        screen.getByText('9,223,372,036,854,775,807원'),
      ).toBeInTheDocument();
    });
  });

  test('does not render Wave 1 forbidden issued-date, free-grade, rate, or max controls', async () => {
    const { container } = render(<RecipientW1cPanel recipientId={42} />);

    await waitFor(() => {
      expect(screen.getByTestId('w1c-panel')).toBeInTheDocument();
    });
    const forbiddenNamedControls = [
      'issued_date',
      'grade_changed_date',
      'benefit_rate',
      'monthly_maximum',
    ];
    for (const name of forbiddenNamedControls) {
      expect(container.querySelector(`[name="${name}"]`)).toBeNull();
    }
    expect(container.querySelector('input[list]')).toBeNull();
    expect(screen.queryByText('인지지원등급')).toBeNull();
    expect(screen.queryByText(/월중 최고/)).toBeNull();
  });
});
