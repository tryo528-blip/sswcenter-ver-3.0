import './setup';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import RecipientServicePlanNoticePanel from '../components/recipients/RecipientServicePlanNoticePanel';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const contract = {
  id: 22,
  recipient_id: 10,
  service_type_code: 'HOME_CARE',
  service_group_code: 'LONG_TERM_CARE',
  start_date: '2026-01-01',
  end_date: '2027-12-31',
  service_start_date: null,
  end_reason_text: null,
  invalidated_at_utc: null,
  replacement_contract_id: null,
  row_version: 1,
};

function notice(rowVersion = 1) {
  return {
    id: 31,
    recipient_id: 10,
    recipient_contract_id: 22,
    notification_date: '2026-08-10',
    applied_start_date: '2026-09-01',
    applied_end_date: '2027-06-30',
    invalidated_at_utc: null,
    replacement_service_plan_notice_id: null,
    row_version: rowVersion,
  };
}

describe('W2 service-plan notice panel', () => {
  afterEach(() => vi.restoreAllMocks());

  it('submits only the approved contract and three date fields', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string'
        ? input
        : input instanceof URL ? input.href : input.url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      if (url.pathname.endsWith('/contracts')) return json({ items: [contract] });
      if (url.pathname.endsWith('/service-plan-notices') && method === 'GET') {
        return json({ items: [] });
      }
      if (url.pathname.endsWith('/service-plan-notices') && method === 'POST') {
        return json(notice(), 201);
      }
      return json({}, 404);
    });

    render(<RecipientServicePlanNoticePanel recipientId="10" />);
    await waitFor(() => expect(screen.getByTestId('service-plan-submit')).toBeEnabled());

    fireEvent.change(screen.getByTestId('service-plan-notification-date-input'), {
      target: { value: '2026-08-10' },
    });
    fireEvent.change(screen.getByTestId('service-plan-applied-start-date-input'), {
      target: { value: '2026-09-01' },
    });
    fireEvent.change(screen.getByTestId('service-plan-applied-end-date-input'), {
      target: { value: '' },
    });
    fireEvent.click(screen.getByTestId('service-plan-submit'));

    await waitFor(() => expect(screen.getByText('급여계획서를 저장했습니다.')).toBeInTheDocument());
    const postCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(postCall).toBeDefined();
    expect(JSON.parse(String(postCall?.[1]?.body))).toEqual({
      recipient_contract_id: 22,
      notification_date: '2026-08-10',
      applied_start_date: '2026-09-01',
      applied_end_date: null,
    });
  });

  it('keeps the correction draft and shows the latest history after a 409', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string'
        ? input
        : input instanceof URL ? input.href : input.url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      if (url.pathname.endsWith('/contracts')) return json({ items: [contract] });
      if (url.pathname.endsWith('/service-plan-notices') && method === 'GET') {
        return json({ items: [notice()] });
      }
      if (url.pathname.endsWith('/service-plan-notices/31') && method === 'PUT') {
        return json({
          error: { code: 'ROW_VERSION_CONFLICT', message: '먼저 변경됨' },
          details: { latest: { items: [notice(8)] } },
        }, 409);
      }
      return json({}, 404);
    });

    render(<RecipientServicePlanNoticePanel recipientId={10} />);
    await waitFor(() => expect(screen.getByTestId('service-plan-correct-31')).toBeEnabled());
    fireEvent.click(screen.getByTestId('service-plan-correct-31'));
    fireEvent.change(screen.getByTestId('service-plan-notification-date-input'), {
      target: { value: '2026-08-12' },
    });
    fireEvent.click(screen.getByTestId('service-plan-submit'));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('입력은 유지');
      expect(screen.getByTestId('service-plan-notification-date-input')).toHaveValue(
        '2026-08-12',
      );
      expect(screen.getByTestId('service-plan-submit')).toHaveTextContent('정정 저장');
    });
  });
});
