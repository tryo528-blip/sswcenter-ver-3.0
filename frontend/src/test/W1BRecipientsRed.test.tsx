import './setup';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import RecipientsPage from '../pages/RecipientsPage';

const syntheticRecipient = {
  id: 'test-recipient-01',
  name: 'TEST_RECIPIENT_READBACK',
  birth_date: '2000-01-01',
  sex_code: 'MALE',
  postal_code: 'TEST-POSTAL-01',
  address: 'TEST_ADDRESS_01',
  home_phone: '010-0000-0001',
  mobile_phone: '010-0000-0002',
  recipient_no: null,
  row_version: 1,
};

const syntheticRecipientDetail = {
  ...syntheticRecipient,
  guardians: [
    {
      id: 'test-guardian-01',
      name: 'TEST_GUARDIAN_01',
      phone: '010-0000-0003',
    },
  ],
};

const recipientCreateFixture = {
  name: 'TEST_RECIPIENT_CREATE',
  birth_date: '2000-01-01',
  sex_code: 'MALE',
  postal_code: 'TEST-POSTAL-01',
  address: 'TEST_ADDRESS_01',
  home_phone: '010-0000-0001',
  mobile_phone: '010-0000-0002',
};
const recipientNoNamedControlSelector = 'input[name="recipient_no"], select[name="recipient_no"], textarea[name="recipient_no"]';
const recipientNoCanonicalInputSelector = '[data-testid="recipient-no-input"]';

function recipientNoContenteditables(root: Element): Element[] {
  return Array.from(root.querySelectorAll<HTMLElement>('[contenteditable]')).filter((element) =>
    ['name', 'data-field', 'data-testid', 'aria-label'].some((attribute) => {
      const value = element.getAttribute(attribute)?.toLowerCase().replace(/-/g, '_');
      return value === 'recipient_no' || value === 'recipient_no_input';
    }),
  );
}

describe('W1B-F2 RED: recipient UI contracts', () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>;
  let recipientPostBody: Record<string, unknown> | null;

  beforeEach(() => {
    recipientPostBody = null;
    fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = typeof input === 'string' ? input : (input as Request).url;
      const requestUrl = new URL(url, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();

      if (requestUrl.pathname === '/api/v1/recipients' && method === 'POST') {
        recipientPostBody = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
        return new Response(JSON.stringify(syntheticRecipientDetail), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (requestUrl.pathname === '/api/v1/recipients/test-recipient-01' && method === 'GET') {
        return new Response(JSON.stringify(syntheticRecipientDetail), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (requestUrl.pathname === '/api/v1/recipients' && method === 'GET') {
        return new Response(
          JSON.stringify({ items: [syntheticRecipient], total: 1, page: 1, page_size: 100 }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      return new Response(JSON.stringify({ detail: { code: 'not_found' } }), { status: 404 });
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  test('calls the real recipient list API resource', async () => {
    render(<RecipientsPage />);

    await waitFor(() => {
      const listCall = fetchSpy.mock.calls.find(([input]) => {
        const url = typeof input === 'string' ? input : (input as Request).url;
        return url.includes('/api/v1/recipients');
      });
      expect(listCall, 'W1B_F2_API_RECIPIENT_LIST_MISSING').toBeDefined();
    });

    const listCall = fetchSpy.mock.calls.find(([input]) => {
      const url = typeof input === 'string' ? input : (input as Request).url;
      return url.includes('/api/v1/recipients');
    });
    const input = listCall?.[0];
    const init = listCall?.[1];
    const url = typeof input === 'string' ? input : (input as Request).url;
    expect(new URL(url, 'http://localhost').pathname, 'W1B_F2_API_RECIPIENT_PATH_DRIFT').toBe(
      '/api/v1/recipients',
    );
    expect(init?.method ?? 'GET', 'W1B_F2_API_RECIPIENT_LIST_METHOD_DRIFT').toBe('GET');
  });

  test('exposes required fields and submits the separated contact payload', async () => {
    render(<RecipientsPage />);

    const form = screen.queryByTestId('recipient-create-form');
    expect(form, 'W1B_F2_REC_REQUIRED_FORM_MISSING').toBeInTheDocument();
    if (!form) return;

    expect(
      form.querySelector(recipientNoCanonicalInputSelector),
      'W1B_F2_RECIPIENT_NO_CANONICAL_INPUT_FORBIDDEN',
    ).toBeNull();
    expect(
      form.querySelectorAll(recipientNoNamedControlSelector).length,
      'W1B_F2_RECIPIENT_NO_NAMED_CONTROL_FORBIDDEN',
    ).toBe(0);
    expect(
      recipientNoContenteditables(form).length,
      'W1B_F2_RECIPIENT_NO_CONTENTEDITABLE_FORBIDDEN',
    ).toBe(0);

    const nameInput = screen.queryByTestId('recipient-name-input');
    const birthDateInput = screen.queryByTestId('recipient-birth-date-input');
    const sexCodeSelect = screen.queryByTestId('recipient-sex-code-select');
    const postalCodeInput = screen.queryByTestId('recipient-postal-code-input');
    const addressInput = screen.queryByTestId('recipient-address-input');
    const homePhoneInput = screen.queryByTestId('recipient-home-phone-input');
    const mobilePhoneInput = screen.queryByTestId('recipient-mobile-phone-input');

    expect(nameInput, 'W1B_F2_REC_NAME_FIELD_MISSING').toBeInTheDocument();
    expect(birthDateInput, 'W1B_F2_REC_BIRTH_DATE_FIELD_MISSING').toBeInTheDocument();
    expect(sexCodeSelect, 'W1B_F2_REC_SEX_CODE_FIELD_MISSING').toBeInTheDocument();
    expect(postalCodeInput, 'W1B_F2_REC_POSTAL_CODE_FIELD_MISSING').toBeInTheDocument();
    expect(addressInput, 'W1B_F2_REC_ADDRESS_FIELD_MISSING').toBeInTheDocument();
    expect(homePhoneInput, 'W1B_F2_REC_HOME_PHONE_FIELD_MISSING').toBeInTheDocument();
    expect(mobilePhoneInput, 'W1B_F2_REC_MOBILE_PHONE_FIELD_MISSING').toBeInTheDocument();
    if (!nameInput || !birthDateInput || !sexCodeSelect || !postalCodeInput || !addressInput || !homePhoneInput || !mobilePhoneInput) {
      return;
    }

    expect(nameInput, 'W1B_F2_REC_NAME_REQUIRED_SEMANTICS_MISSING').toBeRequired();
    expect(birthDateInput, 'W1B_F2_REC_BIRTH_DATE_REQUIRED_SEMANTICS_MISSING').toBeRequired();
    expect(sexCodeSelect, 'W1B_F2_REC_SEX_CODE_REQUIRED_SEMANTICS_MISSING').toBeRequired();
    expect(postalCodeInput, 'W1B_F2_REC_POSTAL_CODE_REQUIRED_SEMANTICS_FORBIDDEN').not.toBeRequired();
    expect(addressInput, 'W1B_F2_REC_ADDRESS_REQUIRED_SEMANTICS_FORBIDDEN').not.toBeRequired();
    expect(homePhoneInput, 'W1B_F2_REC_HOME_PHONE_REQUIRED_SEMANTICS_FORBIDDEN').not.toBeRequired();
    expect(mobilePhoneInput, 'W1B_F2_REC_MOBILE_PHONE_REQUIRED_SEMANTICS_FORBIDDEN').not.toBeRequired();

    const sexOptionValues = Array.from(sexCodeSelect.querySelectorAll('option'))
      .map((option) => option.value)
      .sort();
    expect(sexOptionValues, 'W1B_F2_REC_SEX_CODE_PUBLIC_OPTION_SET_MISMATCH').toEqual(['FEMALE', 'MALE']);

    fireEvent.change(nameInput, { target: { value: recipientCreateFixture.name } });
    fireEvent.change(birthDateInput, { target: { value: recipientCreateFixture.birth_date } });
    fireEvent.change(sexCodeSelect, { target: { value: recipientCreateFixture.sex_code } });
    fireEvent.change(postalCodeInput, { target: { value: recipientCreateFixture.postal_code } });
    fireEvent.change(addressInput, { target: { value: recipientCreateFixture.address } });
    fireEvent.change(homePhoneInput, { target: { value: recipientCreateFixture.home_phone } });
    fireEvent.change(mobilePhoneInput, { target: { value: recipientCreateFixture.mobile_phone } });

    const submitButton = screen.queryByTestId('recipient-submit-button');
    expect(submitButton, 'W1B_F2_REC_SUBMIT_BUTTON_MISSING').toBeInTheDocument();
    if (!submitButton) return;
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(recipientPostBody, 'W1B_F2_REC_CREATE_POST_REQUEST_MISSING').toBeDefined();
    });
    if (!recipientPostBody) return;
    expect(recipientPostBody, 'W1B_F2_REC_CREATE_POST_BODY_FIELDS_MISMATCH').toMatchObject(recipientCreateFixture);
    expect(
      Object.prototype.hasOwnProperty.call(recipientPostBody, 'recipient_no'),
      'W1B_F2_RECIPIENT_NO_CREATE_POST_KEY_FORBIDDEN',
    ).toBe(false);
    expect(recipientPostBody.home_phone, 'W1B_F2_REC_HOME_MOBILE_PAYLOAD_COLLISION').not.toBe(
      recipientPostBody.mobile_phone,
    );
    expect(recipientPostBody.home_phone, 'W1B_F2_REC_HOME_PHONE_GUARDIAN_CONFUSION').not.toBe('010-0000-0003');
    expect(recipientPostBody.mobile_phone, 'W1B_F2_REC_MOBILE_PHONE_GUARDIAN_CONFUSION').not.toBe('010-0000-0003');
  });

  test('keeps phone fields separate and reads list/detail contact surfaces back', async () => {
    render(<RecipientsPage />);

    const listSurface = screen.queryByTestId('recipient-list');
    expect(
      screen.queryByTestId('recipient-home-phone-input'),
      'W1B_F2_PHONE_RECIPIENT_HOME_FIELD_MISSING',
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId('recipient-mobile-phone-input'),
      'W1B_F2_PHONE_RECIPIENT_MOBILE_FIELD_MISSING',
    ).toBeInTheDocument();
    const guardianPhoneInput = screen.queryByTestId('guardian-phone-input');
    expect(guardianPhoneInput, 'W1B_F2_PHONE_GUARDIAN_FIELD_MISSING').toBeInTheDocument();
    expect(
      guardianPhoneInput,
      'W1B_F2_GUARDIAN_PHONE_REQUIRED_SEMANTICS_FORBIDDEN',
    ).not.toBeRequired();
    expect(listSurface, 'W1B_F2_CONTACT_LIST_SURFACE_MISSING').toBeInTheDocument();
    if (!listSurface || !guardianPhoneInput) return;

    await waitFor(() => {
      const listCall = fetchSpy.mock.calls.find(([input, init]) => {
        const url = typeof input === 'string' ? input : (input as Request).url;
        const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
        return new URL(url, 'http://localhost').pathname === '/api/v1/recipients' && method === 'GET';
      });
      expect(listCall, 'W1B_F2_CONTACT_LIST_READ_REQUEST_MISSING').toBeDefined();
    });

    expect(screen.queryByTestId('recipient-list-home-phone'), 'W1B_F2_CONTACT_LIST_HOME_READBACK_MISSING').toHaveTextContent(
      syntheticRecipient.home_phone,
    );
    expect(screen.queryByTestId('recipient-list-mobile-phone'), 'W1B_F2_CONTACT_LIST_MOBILE_READBACK_MISSING').toHaveTextContent(
      syntheticRecipient.mobile_phone,
    );
    expect(screen.queryByTestId('recipient-list-address'), 'W1B_F2_CONTACT_LIST_ADDRESS_READBACK_MISSING').toHaveTextContent(
      syntheticRecipient.address,
    );
    const listRecipientNo = screen.queryByTestId('recipient-list-recipient-no');
    expect(listRecipientNo, 'W1B_F2_RECIPIENT_NO_LIST_SURFACE_MISSING').toBeInTheDocument();
    expect(listRecipientNo?.textContent?.trim(), 'W1B_F2_RECIPIENT_NO_LIST_UNASSIGNED_DISPLAY_MISSING').toBe('미부여');
    if (!listRecipientNo) return;
    expect(
      listSurface.querySelectorAll(recipientNoNamedControlSelector).length,
      'W1B_F2_RECIPIENT_NO_LIST_NAMED_CONTROL_FORBIDDEN',
    ).toBe(0);
    expect(
      listSurface.querySelector(recipientNoCanonicalInputSelector),
      'W1B_F2_RECIPIENT_NO_LIST_CANONICAL_INPUT_FORBIDDEN',
    ).toBeNull();
    expect(
      recipientNoContenteditables(listSurface).length,
      'W1B_F2_RECIPIENT_NO_LIST_CONTENTEDITABLE_FORBIDDEN',
    ).toBe(0);
    expect(guardianPhoneInput, 'W1B_F2_GUARDIAN_PHONE_VALUE_MISSING').toHaveValue('010-0000-0003');

    const nameOption = screen.queryByTestId('recipient-name-option');
    expect(nameOption, 'W1B_F2_CONTACT_DETAIL_SELECTION_TARGET_MISSING').toBeInTheDocument();
    if (!nameOption) return;
    fireEvent.click(nameOption);
    await waitFor(() => {
      expect(screen.queryByTestId('recipient-detail-workspace'), 'W1B_F2_CONTACT_DETAIL_WORKSPACE_MISSING').toBeInTheDocument();
    });
    const detailWorkspace = screen.queryByTestId('recipient-detail-workspace');
    expect(screen.queryByTestId('recipient-detail-home-phone'), 'W1B_F2_CONTACT_DETAIL_HOME_READBACK_MISSING').toHaveTextContent(
      syntheticRecipientDetail.home_phone,
    );
    expect(screen.queryByTestId('recipient-detail-mobile-phone'), 'W1B_F2_CONTACT_DETAIL_MOBILE_READBACK_MISSING').toHaveTextContent(
      syntheticRecipientDetail.mobile_phone,
    );
    expect(screen.queryByTestId('recipient-detail-address'), 'W1B_F2_CONTACT_DETAIL_ADDRESS_READBACK_MISSING').toHaveTextContent(
      syntheticRecipientDetail.address,
    );
    const detailRecipientNo = screen.queryByTestId('recipient-detail-recipient-no');
    expect(detailRecipientNo, 'W1B_F2_RECIPIENT_NO_DETAIL_SURFACE_MISSING').toBeInTheDocument();
    expect(detailRecipientNo?.textContent?.trim(), 'W1B_F2_RECIPIENT_NO_DETAIL_UNASSIGNED_DISPLAY_MISSING').toBe('미부여');
    if (!detailWorkspace || !detailRecipientNo) return;
    expect(
      detailWorkspace.querySelectorAll(recipientNoNamedControlSelector).length,
      'W1B_F2_RECIPIENT_NO_DETAIL_NAMED_CONTROL_FORBIDDEN',
    ).toBe(0);
    expect(
      detailWorkspace.querySelector(recipientNoCanonicalInputSelector),
      'W1B_F2_RECIPIENT_NO_DETAIL_CANONICAL_INPUT_FORBIDDEN',
    ).toBeNull();
    expect(
      recipientNoContenteditables(detailWorkspace).length,
      'W1B_F2_RECIPIENT_NO_DETAIL_CONTENTEDITABLE_FORBIDDEN',
    ).toBe(0);
    expect(screen.queryByTestId('recipient-detail-home-phone'), 'W1B_F2_CONTACT_DETAIL_GUARDIAN_CONFUSION').not.toHaveTextContent(
      '010-0000-0003',
    );
  });

  test('renders representative guardian history as its own contract', () => {
    render(<RecipientsPage />);

    expect(
      screen.queryByTestId('recipient-primary-guardian-history'),
      'W1B_F2_PRIMARY_GUARDIAN_HISTORY_MISSING',
    ).toBeInTheDocument();
  });

  test('renders payer snapshots independently from guardian data', () => {
    render(<RecipientsPage />);

    const payerSection = screen.queryByTestId('recipient-payer-snapshot-section');
    expect(payerSection, 'W1B_F2_PAYER_SNAPSHOT_SECTION_MISSING').toBeInTheDocument();
    expect(
      screen.queryByTestId('recipient-payer-name-input'),
      'W1B_F2_PAYER_NAME_SURFACE_MISSING',
    ).toBeInTheDocument();
    expect(screen.queryByTestId('recipient-payer-type-select'), 'W1B_F2_PAYER_TYPE_FORBIDDEN').not.toBeInTheDocument();

    const payerMarkup = payerSection?.innerHTML ?? '';
    expect(payerMarkup, 'W1B_F2_PAYER_TYPE_TOKEN_FORBIDDEN').not.toMatch(/payer_type/i);
    expect(payerMarkup, 'W1B_F2_PAYER_GUARDIAN_ROLE_TOKEN_FORBIDDEN').not.toMatch(/SELF|PRIMARY_GUARDIAN/i);
  });

  test('preserves name selection list context for a detail workspace', async () => {
    render(<RecipientsPage />);

    const nameOption = await screen.findByTestId('recipient-name-option');
    expect(nameOption, 'W1B_F2_NAME_SELECTION_CONTEXT_MISSING').toBeInTheDocument();
    expect(screen.queryByTestId('recipient-detail-workspace'), 'W1B_F2_DETAIL_WORKSPACE_MISSING').toBeInTheDocument();
  });

  test('keeps recipient selection in the same window and forbids popups', async () => {
    const windowOpenSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    render(<RecipientsPage />);

    const nameOption = await screen.findByTestId('recipient-name-option');
    expect(nameOption, 'W1B_F2_POPUP_ZERO_SELECTION_TARGET_MISSING').toBeInTheDocument();
    if (!nameOption) return;

    fireEvent.click(nameOption);
    expect(windowOpenSpy, 'W1B_F2_POPUP_ZERO_CONTRACT_BROKEN').not.toHaveBeenCalled();
    expect(screen.queryByTestId('recipient-detail-workspace'), 'W1B_F2_POPUP_ZERO_DETAIL_MISSING').toBeInTheDocument();
  });

  test('does not count forbidden-field absence as GREEN without the recipient surface', () => {
    render(<RecipientsPage />);

    const recipientSurface = screen.queryByTestId('recipient-list');
    expect(recipientSurface, 'W1B_F2_ABS_SURFACE_MISSING_FALSE_GREEN_GUARD').toBeInTheDocument();
    if (!recipientSurface) return;

    const surfaceMarkup = recipientSurface.innerHTML;
    const surfaceText = recipientSurface.textContent ?? '';
    expect(surfaceMarkup, 'W1B_F2_ABS_LEGACY_FIELD_LEAK').not.toMatch(/legacy_|payer_type|guardian_id/i);
    expect(surfaceText, 'W1B_F2_ABS_MONTHLY_SCHEDULE_PLACEHOLDER').not.toMatch(/월간 일정|팝업|window\.open/i);
    expect(surfaceText, 'W1B_F2_ABS_FAKE_RECIPIENT_CONTRACT_ROW').not.toMatch(
      /인정번호|장기요양|서비스 그룹|계약|방문요양|방문목욕|L1234567890|3등급/i,
    );
  });
});
