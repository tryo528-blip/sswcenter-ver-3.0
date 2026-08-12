/**
 * W1D Phase-2 P2A-R4/R5/R6/R7: RecipientContractPanel state discard + races.
 * Direct component test; mocks w1dApi. maxWorkers=1 via package script / CLI.
 */
import './setup';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, test, vi } from 'vitest';
import RecipientContractPanel from '../components/recipients/RecipientContractPanel';

const listContracts = vi.fn();
const previewCertificationTransition = vi.fn();
const applyCertificationTransition = vi.fn();
const createContract = vi.fn();

vi.mock('../services/w1dApi', () => ({
  ApiError: class ApiError extends Error {
    status: number;
    code?: string;
    constructor(message: string, status = 400, code?: string) {
      super(message);
      this.status = status;
      this.code = code;
    }
  },
  listContracts: (...args: unknown[]) => listContracts(...args),
  previewCertificationTransition: (...args: unknown[]) =>
    previewCertificationTransition(...args),
  applyCertificationTransition: (...args: unknown[]) =>
    applyCertificationTransition(...args),
  createContract: (...args: unknown[]) => createContract(...args),
}));

const openLtcContract = {
  id: 10,
  recipient_id: 1,
  service_type_code: 'HOME_CARE',
  service_group_code: 'LONG_TERM_CARE',
  start_date: '2025-01-01',
  end_date: null,
  service_start_date: null,
  signer_name: null,
  signer_relationship_text: null,
  signer_phone: null,
  end_reason_text: null,
  invalidated_at_utc: null,
  replacement_contract_id: null,
  row_version: 1,
};

const previewResponse = {
  preview_token: 'TOK_A',
  canonical_hash: 'hash-a',
  serialization_version: 'w1d-transition-v1',
  proposed_end_date: '2026-06-30',
  affected_certification_period_ids: [1],
  affected_grade_period_ids: [1],
  affected_contract_ids: [10],
  service_multiset: ['HOME_CARE'],
  replacement_preview: [
    {
      ended_contract_id: 10,
      service_type_code: 'HOME_CARE',
      start_date: '2026-07-01',
      end_date: null,
    },
  ],
};

function fillTransitionDates() {
  fireEvent.change(screen.getByTestId('transition-new-start-date'), {
    target: { value: '2026-07-01' },
  });
  fireEvent.change(screen.getByTestId('transition-new-end-date'), {
    target: { value: '2027-06-30' },
  });
  fireEvent.change(screen.getByTestId('transition-new-grade-start-date'), {
    target: { value: '2026-07-01' },
  });
  fireEvent.change(screen.getByTestId('transition-new-grade-end-date'), {
    target: { value: '2027-06-30' },
  });
}

async function buildPopulatedPreviewAndConfirm() {
  await waitFor(() => {
    expect(listContracts).toHaveBeenCalled();
  });
  // Ensure list has painted so preview builds LTC replacements.
  await waitFor(() => {
    expect(screen.getByTestId('contract-row-10')).toBeInTheDocument();
  });
  fillTransitionDates();
  fireEvent.click(screen.getByTestId('transition-preview-button'));
  await waitFor(() => {
    expect(screen.getByTestId('transition-impact-list')).toBeInTheDocument();
  });
  const confirm = screen.getByTestId(
    'transition-confirm-checkbox',
  ) as HTMLInputElement;
  expect(confirm.disabled).toBe(false);
  fireEvent.click(confirm);
  expect(confirm.checked).toBe(true);
  expect(
    (screen.getByTestId('transition-apply-button') as HTMLButtonElement)
      .disabled,
  ).toBe(false);
}

describe('RecipientContractPanel state (P2A-R4/R5/R6/R7)', () => {
  beforeEach(() => {
    listContracts.mockReset();
    previewCertificationTransition.mockReset();
    applyCertificationTransition.mockReset();
    createContract.mockReset();
    listContracts.mockResolvedValue({ items: [openLtcContract] });
    previewCertificationTransition.mockResolvedValue(previewResponse);
    applyCertificationTransition.mockResolvedValue({
      recipient_id: 1,
      new_contract_ids: [11],
      audit_correlation_id: '00000000-0000-4000-8000-000000000099',
    });
  });

  test('editing a token-contributing transition input discards preview and confirmation', async () => {
    render(
      <RecipientContractPanel recipientId={1} recipientNo="R-1" />,
    );

    await buildPopulatedPreviewAndConfirm();

    // Any of the five token fields must drop preview + confirmation.
    fireEvent.change(screen.getByTestId('transition-new-start-date'), {
      target: { value: '2026-08-01' },
    });

    expect(screen.queryByTestId('transition-impact-list')).toBeNull();
    expect(
      (screen.getByTestId('transition-confirm-checkbox') as HTMLInputElement)
        .checked,
    ).toBe(false);
    expect(
      (screen.getByTestId('transition-apply-button') as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  test('deferred old preview must not restore after token input edit', async () => {
    let resolveOldPreview: (value: typeof previewResponse) => void = () =>
      undefined;
    const oldPreviewPromise = new Promise<typeof previewResponse>((resolve) => {
      resolveOldPreview = resolve;
    });

    previewCertificationTransition.mockImplementationOnce(
      () => oldPreviewPromise,
    );

    render(
      <RecipientContractPanel recipientId={1} recipientNo="R-1" />,
    );

    await waitFor(() => {
      expect(screen.getByTestId('contract-row-10')).toBeInTheDocument();
    });
    fillTransitionDates();
    fireEvent.click(screen.getByTestId('transition-preview-button'));
    expect(previewCertificationTransition).toHaveBeenCalledTimes(1);

    // Change a token-contributing field while the first preview is still in flight.
    fireEvent.change(screen.getByTestId('transition-new-start-date'), {
      target: { value: '2026-08-01' },
    });

    expect(screen.queryByTestId('transition-impact-list')).toBeNull();
    expect(
      (screen.getByTestId('transition-apply-button') as HTMLButtonElement)
        .disabled,
    ).toBe(true);

    // Late resolution of the old preview must not repopulate impact/token/confirm.
    await act(async () => {
      resolveOldPreview(previewResponse);
      await Promise.resolve();
    });

    expect(screen.queryByTestId('transition-impact-list')).toBeNull();
    expect(
      (screen.getByTestId('transition-confirm-checkbox') as HTMLInputElement)
        .checked,
    ).toBe(false);
    expect(
      (screen.getByTestId('transition-apply-button') as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  test('recipientId change after populated preview+confirm resets state; late old list ignored', async () => {
    let resolveOldList: (value: { items: typeof openLtcContract[] }) => void =
      () => undefined;
    const oldListPromise = new Promise<{ items: typeof openLtcContract[] }>(
      (resolve) => {
        resolveOldList = resolve;
      },
    );

    // First load for recipient 1 resolves immediately so preview can be built.
    listContracts.mockImplementation((id: number | string) => {
      if (String(id) === '1') {
        return Promise.resolve({ items: [openLtcContract] });
      }
      return Promise.resolve({
        items: [
          {
            ...openLtcContract,
            id: 99,
            recipient_id: 2,
            service_type_code: 'HOME_BATH',
          },
        ],
      });
    });

    const { rerender } = render(
      <RecipientContractPanel recipientId={1} recipientNo="R-1" />,
    );

    await buildPopulatedPreviewAndConfirm();
    expect(screen.getByTestId('transition-impact-list')).toBeInTheDocument();

    // Subsequent load for recipient 1 (if any) hangs; recipient 2 resolves.
    listContracts.mockImplementation((id: number | string) => {
      if (String(id) === '1') {
        return oldListPromise;
      }
      return Promise.resolve({
        items: [
          {
            ...openLtcContract,
            id: 99,
            recipient_id: 2,
            service_type_code: 'HOME_BATH',
          },
        ],
      });
    });

    // Also seed a deferred create-path list call via hanging old id if re-triggered.
    fireEvent.change(screen.getByTestId('contract-start-date-input'), {
      target: { value: '2026-01-15' },
    });
    fireEvent.change(screen.getByTestId('contract-signer-name-input'), {
      target: { value: 'DraftSigner' },
    });

    rerender(<RecipientContractPanel recipientId={2} recipientNo="R-2" />);

    await waitFor(() => {
      expect(listContracts).toHaveBeenCalledWith(2);
    });

    // Drafts, preview, confirmation fully reset for new recipient.
    expect(
      (screen.getByTestId('contract-start-date-input') as HTMLInputElement)
        .value,
    ).toBe('');
    expect(
      (screen.getByTestId('contract-signer-name-input') as HTMLInputElement)
        .value,
    ).toBe('');
    expect(
      (screen.getByTestId('transition-new-start-date') as HTMLInputElement)
        .value,
    ).toBe('');
    expect(
      (screen.getByTestId('transition-new-grade-code') as HTMLSelectElement)
        .value,
    ).toBe('4');
    expect(screen.queryByTestId('transition-impact-list')).toBeNull();
    expect(
      (screen.getByTestId('transition-confirm-checkbox') as HTMLInputElement)
        .checked,
    ).toBe(false);
    expect(
      (screen.getByTestId('transition-apply-button') as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(screen.getByTestId('contract-recipient-no-display').textContent).toContain(
      'R-2',
    );

    await waitFor(() => {
      expect(screen.getByTestId('contract-row-99')).toBeInTheDocument();
    });

    // Late resolution of recipient-1 list must not overwrite recipient-2 panel.
    await act(async () => {
      resolveOldList({
        items: [
          {
            ...openLtcContract,
            id: 10,
            recipient_id: 1,
            service_type_code: 'HOME_CARE',
          },
        ],
      });
      await Promise.resolve();
    });

    expect(screen.getByTestId('contract-row-99')).toBeInTheDocument();
    expect(screen.queryByTestId('contract-row-10')).toBeNull();
    expect(screen.getByTestId('contract-row-99').textContent).toContain(
      'HOME_BATH',
    );
  });

  test('re-preview immediately discards old resolved preview/token; only latest repopulates', async () => {
    const secondPreviewResponse = {
      ...previewResponse,
      preview_token: 'TOK_B',
      canonical_hash: 'hash-b',
      proposed_end_date: '2026-07-31',
      affected_contract_ids: [10, 20],
    };

    let resolveSecond: (value: typeof secondPreviewResponse) => void = () =>
      undefined;
    const secondPromise = new Promise<typeof secondPreviewResponse>(
      (resolve) => {
        resolveSecond = resolve;
      },
    );

    // First preview resolves immediately (default mock); second is deferred.
    previewCertificationTransition
      .mockResolvedValueOnce(previewResponse)
      .mockImplementationOnce(() => secondPromise);

    render(
      <RecipientContractPanel recipientId={1} recipientNo="R-1" />,
    );

    await buildPopulatedPreviewAndConfirm();
    expect(screen.getByTestId('transition-impact-list').textContent).toContain(
      '10',
    );
    expect(previewCertificationTransition).toHaveBeenCalledTimes(1);

    // Start second preview while first is fully resolved + confirmed.
    fireEvent.click(screen.getByTestId('transition-preview-button'));
    expect(previewCertificationTransition).toHaveBeenCalledTimes(2);

    // Old impact/token/confirm must drop immediately; apply cannot use TOK_A.
    expect(screen.queryByTestId('transition-impact-list')).toBeNull();
    const confirmDuring = screen.getByTestId(
      'transition-confirm-checkbox',
    ) as HTMLInputElement;
    expect(confirmDuring.checked).toBe(false);
    expect(confirmDuring.disabled).toBe(true);
    const applyDuring = screen.getByTestId(
      'transition-apply-button',
    ) as HTMLButtonElement;
    expect(applyDuring.disabled).toBe(true);

    fireEvent.click(applyDuring);
    expect(applyCertificationTransition).not.toHaveBeenCalled();

    // Latest response only may repopulate; confirmation must be fresh.
    await act(async () => {
      resolveSecond(secondPreviewResponse);
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(screen.getByTestId('transition-impact-list')).toBeInTheDocument();
    });
    expect(screen.getByTestId('transition-impact-list').textContent).toContain(
      '10, 20',
    );
    expect(
      screen.getByTestId('transition-proposed-end-date').textContent,
    ).toContain('2026-07-31');
    const confirmAfter = screen.getByTestId(
      'transition-confirm-checkbox',
    ) as HTMLInputElement;
    expect(confirmAfter.disabled).toBe(false);
    expect(confirmAfter.checked).toBe(false);
    expect(
      (screen.getByTestId('transition-apply-button') as HTMLButtonElement)
        .disabled,
    ).toBe(true);

    // Fresh confirmation enables apply with the new token only.
    fireEvent.click(confirmAfter);
    fireEvent.click(screen.getByTestId('transition-apply-button'));
    await waitFor(() => {
      expect(applyCertificationTransition).toHaveBeenCalledTimes(1);
    });
    const applyBody = applyCertificationTransition.mock.calls[0][1] as {
      preview_token: string;
      confirmed: boolean;
    };
    expect(applyBody.preview_token).toBe('TOK_B');
    expect(applyBody.confirmed).toBe(true);
  });

  test('late apply A success must not clear newer same-recipient preview B', async () => {
    let resolveApplyA: (value: unknown) => void = () => undefined;
    const applyAPromise = new Promise((resolve) => {
      resolveApplyA = resolve;
    });

    const previewB = {
      ...previewResponse,
      preview_token: 'TOK_B',
      canonical_hash: 'hash-b',
      proposed_end_date: '2026-08-15',
      affected_contract_ids: [10, 30],
    };

    previewCertificationTransition
      .mockResolvedValueOnce(previewResponse)
      .mockResolvedValueOnce(previewB);
    applyCertificationTransition.mockImplementationOnce(() => applyAPromise);

    render(
      <RecipientContractPanel recipientId={1} recipientNo="R-1" />,
    );

    await buildPopulatedPreviewAndConfirm();
    expect(screen.getByTestId('transition-impact-list').textContent).toContain(
      '10',
    );

    // Start apply A (token A) while deferring resolution.
    fireEvent.click(screen.getByTestId('transition-apply-button'));
    expect(applyCertificationTransition).toHaveBeenCalledTimes(1);
    const applyABody = applyCertificationTransition.mock.calls[0][1] as {
      preview_token: string;
    };
    expect(applyABody.preview_token).toBe('TOK_A');

    // Build preview B on the same recipient while A is in flight.
    // Apply A bumped generation and discarded is not automatic — re-preview
    // starts a new generation and discards old resolved state immediately.
    fillTransitionDates();
    fireEvent.click(screen.getByTestId('transition-preview-button'));
    await waitFor(() => {
      expect(screen.getByTestId('transition-impact-list').textContent).toContain(
        '10, 30',
      );
    });
    expect(
      (screen.getByTestId('transition-confirm-checkbox') as HTMLInputElement)
        .checked,
    ).toBe(false);

    // Late success of A must not wipe B.
    await act(async () => {
      resolveApplyA({
        recipient_id: 1,
        new_contract_ids: [11],
        audit_correlation_id: '00000000-0000-4000-8000-0000000000aa',
      });
      await Promise.resolve();
    });

    expect(screen.getByTestId('transition-impact-list').textContent).toContain(
      '10, 30',
    );
    expect(screen.queryByTestId('transition-stale-banner')).toBeNull();
    expect(screen.queryByTestId('contract-error')).toBeNull();
    expect(
      (screen.getByTestId('transition-confirm-checkbox') as HTMLInputElement)
        .checked,
    ).toBe(false);

    // Fresh confirmation of B applies TOK_B only.
    fireEvent.click(screen.getByTestId('transition-confirm-checkbox'));
    applyCertificationTransition.mockResolvedValueOnce({
      recipient_id: 1,
      new_contract_ids: [12],
      audit_correlation_id: '00000000-0000-4000-8000-0000000000bb',
    });
    fireEvent.click(screen.getByTestId('transition-apply-button'));
    await waitFor(() => {
      expect(applyCertificationTransition).toHaveBeenCalledTimes(2);
    });
    const applyBBody = applyCertificationTransition.mock.calls[1][1] as {
      preview_token: string;
    };
    expect(applyBBody.preview_token).toBe('TOK_B');
  });

  test('late apply A 409 must not overwrite newer preview B with stale banner', async () => {
    let rejectApplyA: (err: Error) => void = () => undefined;
    const applyAPromise = new Promise((_resolve, reject) => {
      rejectApplyA = reject;
    });

    const previewB = {
      ...previewResponse,
      preview_token: 'TOK_B',
      proposed_end_date: '2026-09-01',
      affected_contract_ids: [99],
    };

    previewCertificationTransition
      .mockResolvedValueOnce(previewResponse)
      .mockResolvedValueOnce(previewB);
    applyCertificationTransition.mockImplementationOnce(() => applyAPromise);

    render(
      <RecipientContractPanel recipientId={1} recipientNo="R-1" />,
    );
    await buildPopulatedPreviewAndConfirm();
    fireEvent.click(screen.getByTestId('transition-apply-button'));

    fillTransitionDates();
    fireEvent.click(screen.getByTestId('transition-preview-button'));
    await waitFor(() => {
      expect(screen.getByTestId('transition-impact-list').textContent).toContain(
        '99',
      );
    });

    const { ApiError } = await import('../services/w1dApi');
    await act(async () => {
      rejectApplyA(
        new ApiError('stale', 409, 'CERTIFICATION_TRANSITION_STALE'),
      );
      await Promise.resolve();
    });

    expect(screen.getByTestId('transition-impact-list').textContent).toContain(
      '99',
    );
    expect(screen.queryByTestId('transition-stale-banner')).toBeNull();
    expect(screen.queryByTestId('contract-error')).toBeNull();
  });

  test('late apply A non-409 error must not overwrite newer preview B', async () => {
    let rejectApplyA: (err: Error) => void = () => undefined;
    const applyAPromise = new Promise((_resolve, reject) => {
      rejectApplyA = reject;
    });

    const previewB = {
      ...previewResponse,
      preview_token: 'TOK_B',
      affected_contract_ids: [77],
    };

    previewCertificationTransition
      .mockResolvedValueOnce(previewResponse)
      .mockResolvedValueOnce(previewB);
    applyCertificationTransition.mockImplementationOnce(() => applyAPromise);

    render(
      <RecipientContractPanel recipientId={1} recipientNo="R-1" />,
    );
    await buildPopulatedPreviewAndConfirm();
    fireEvent.click(screen.getByTestId('transition-apply-button'));

    fillTransitionDates();
    fireEvent.click(screen.getByTestId('transition-preview-button'));
    await waitFor(() => {
      expect(screen.getByTestId('transition-impact-list').textContent).toContain(
        '77',
      );
    });

    const { ApiError } = await import('../services/w1dApi');
    await act(async () => {
      rejectApplyA(new ApiError('apply failed', 422, 'VALIDATION_ERROR'));
      await Promise.resolve();
    });

    expect(screen.getByTestId('transition-impact-list').textContent).toContain(
      '77',
    );
    expect(screen.queryByTestId('contract-error')).toBeNull();
    expect(screen.queryByTestId('transition-stale-banner')).toBeNull();
  });
});
