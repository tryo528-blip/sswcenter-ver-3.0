import { expect, test, type Locator, type Page } from 'playwright/test';

test.use({
  trace: 'off',
  video: 'off',
  screenshot: 'off',
});

test.beforeEach(async ({ page }) => {
  await page.route('**/api/bootstrap/status', async (route) => {
    await route.fulfill({ json: { bootstrap_required: false } });
  });
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({
      json: { account: { id: 1, display_name: 'TEST_ADMIN', role_code: 'ADMIN' } },
    });
  });
});

const syntheticRecipientNames = ['TEST_RECIPIENT_ALPHA', 'TEST_RECIPIENT_BETA'];
const syntheticRecipientCreate = {
  name: 'TEST_RECIPIENT_CREATE',
  birth_date: '2000-01-01',
  sex_code: 'MALE',
  postal_code: 'TEST-POSTAL-01',
  address: 'TEST_ADDRESS_01',
  home_phone: '010-0000-0001',
  mobile_phone: '010-0000-0002',
};
const syntheticRecipientReadback = {
  id: 'test-recipient-readback',
  name: 'TEST_RECIPIENT_READBACK',
  birth_date: '2000-01-01',
  sex_code: 'MALE',
  postal_code: 'TEST-POSTAL-01',
  address: 'TEST_ADDRESS_01',
  home_phone: '010-0000-0001',
  mobile_phone: '010-0000-0002',
  recipient_no: null,
  row_version: 1,
  guardians: [{ id: 'test-guardian-01', name: 'TEST_GUARDIAN_01', phone: '010-0000-0003' }],
};
const recipientNoNamedControlSelector = 'input[name="recipient_no"], select[name="recipient_no"], textarea[name="recipient_no"]';
const recipientNoCanonicalInputSelector = '[data-testid="recipient-no-input"]';
const recipientNoContenteditableSelector =
  '[contenteditable][name="recipient_no"], [contenteditable][data-field="recipient_no"], [contenteditable][data-field="recipient-no"], [contenteditable][data-testid="recipient-no-input"], [contenteditable][aria-label="recipient_no"], [contenteditable][aria-label="recipient-no"]';

async function hasRequiredSemantics(locator: Locator): Promise<boolean> {
  return locator.evaluate(
    (element) => element.matches(':required') || element.getAttribute('aria-required') === 'true',
  );
}

async function mockSyntheticRecipientList(page: Page): Promise<void> {
  await page.route(/\/api\/v1\/recipients(?:\/[^?]*)?(?:\?.*)?$/, async (route) => {
    const requestUrl = new URL(route.request().url());
    const method = route.request().method();
    const detailMatch = requestUrl.pathname.match(/^\/api\/v1\/recipients\/test-recipient-(\d+)$/);
    if (detailMatch && method === 'GET') {
      const index = Number(detailMatch[1]) - 1;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        json: {
          id: `test-recipient-${index + 1}`,
          name: syntheticRecipientNames[index],
          birth_date: `2000-01-0${index + 1}`,
          sex_code: index === 0 ? 'MALE' : 'FEMALE',
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: null,
          memo: null,
          recipient_no: null,
          row_version: 1,
        },
      });
      return;
    }
    if (
      /^\/api\/v1\/recipients\/test-recipient-\d+\/(guardians|primary-guardian-periods|payer-snapshots)$/.test(
        requestUrl.pathname,
      ) && method === 'GET'
    ) {
      await route.fulfill({ status: 200, contentType: 'application/json', json: { items: [] } });
      return;
    }
    if (requestUrl.pathname !== '/api/v1/recipients' || method !== 'GET') {
      await route.continue();
      return;
    }

    const pageNumber = Number(requestUrl.searchParams.get('page') ?? '1');

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: syntheticRecipientNames.map((name, index) => ({
          id: `test-recipient-${index + 1}`,
          name,
          birth_date: `2000-01-0${index + 1}`,
          sex_code: index === 0 ? 'MALE' : 'FEMALE',
          phone: null,
          recipient_no: null,
          row_version: 1,
        })),
        total: syntheticRecipientNames.length,
        page: pageNumber,
        page_size: 100,
      }),
    });
  });
}

async function mockRecipientContactReadback(page: Page): Promise<void> {
  await page.route(/\/api\/v1\/recipients(?:\/[^?]*)?(?:\?.*)?$/, async (route) => {
    const request = route.request();
    const requestUrl = new URL(request.url());
    const method = request.method();
    if (requestUrl.pathname === '/api/v1/recipients' && method === 'POST') {
      await route.fulfill({ status: 201, contentType: 'application/json', json: syntheticRecipientReadback });
      return;
    }
    if (requestUrl.pathname === '/api/v1/recipients/test-recipient-readback' && method === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', json: syntheticRecipientReadback });
      return;
    }
    if (requestUrl.pathname === '/api/v1/recipients/test-recipient-readback/guardians' && method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        json: { items: syntheticRecipientReadback.guardians },
      });
      return;
    }
    if (
      /^\/api\/v1\/recipients\/test-recipient-readback\/(primary-guardian-periods|payer-snapshots)$/.test(
        requestUrl.pathname,
      ) && method === 'GET'
    ) {
      await route.fulfill({ status: 200, contentType: 'application/json', json: { items: [] } });
      return;
    }
    if (requestUrl.pathname === '/api/v1/recipients' && method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        json: { items: [syntheticRecipientReadback], total: 1, page: 1, page_size: 100 },
      });
      return;
    }
    await route.continue();
  });
}

async function openRecipients(page: Page, path = '/recipients') {
  await page.goto(path);
  await expect(page.getByTestId('page-recipients'), 'W1B_F2_RECIPIENT_ROUTE_MISSING').toBeVisible();
}

async function openRecipientCreate(page: Page): Promise<void> {
  const form = page.getByTestId('recipient-create-form');
  if (!(await form.isVisible())) {
    await page.getByTestId('recipient-create-toggle').click();
  }
  await expect(form, 'W1B_F2_E2E_REC_REQUIRED_FORM_MISSING').toBeVisible();
}

test.describe('W1B-F2 RED: recipient browser contracts', () => {
  test('reaches the real recipient list API instead of a static placeholder', async ({ page }) => {
    let recipientRequestUrl: string | null = null;
    page.on('request', (request) => {
      const pathname = new URL(request.url()).pathname;
      if (pathname === '/api/v1/recipients' && request.method() === 'GET') {
        recipientRequestUrl = request.url();
      }
    });

    await openRecipients(page);
    await expect
      .poll(() => recipientRequestUrl, {
        timeout: 3000,
        message: 'W1B_F2_API_RECIPIENT_LIST_MISSING_REAL_BROWSER_REQUEST',
      })
      .toBeTruthy();
  });

  test('exposes the required three fields in the create surface', async ({ page }) => {
    await mockRecipientContactReadback(page);
    await openRecipients(page);
    await openRecipientCreate(page);
    const form = page.getByTestId('recipient-create-form');
    await expect(
      form.locator(recipientNoCanonicalInputSelector),
      'W1B_F2_E2E_RECIPIENT_NO_CANONICAL_INPUT_FORBIDDEN',
    ).toHaveCount(0);
    await expect(
      form.locator(recipientNoNamedControlSelector),
      'W1B_F2_E2E_RECIPIENT_NO_NAMED_CONTROL_FORBIDDEN',
    ).toHaveCount(0);
    await expect(
      form.locator(recipientNoContenteditableSelector),
      'W1B_F2_E2E_RECIPIENT_NO_CONTENTEDITABLE_FORBIDDEN',
    ).toHaveCount(0);
    const nameInput = page.getByTestId('recipient-name-input');
    const birthDateInput = page.getByTestId('recipient-birth-date-input');
    const sexCodeSelect = page.getByTestId('recipient-sex-code-select');
    const postalCodeInput = page.getByTestId('recipient-postal-code-input');
    const addressInput = page.getByTestId('recipient-address-input');
    const homePhoneInput = page.getByTestId('recipient-home-phone-input');
    const mobilePhoneInput = page.getByTestId('recipient-mobile-phone-input');
    await expect(nameInput, 'W1B_F2_E2E_REC_NAME_FIELD_MISSING').toBeVisible();
    await expect(birthDateInput, 'W1B_F2_E2E_REC_BIRTH_DATE_FIELD_MISSING').toBeVisible();
    await expect(sexCodeSelect, 'W1B_F2_E2E_REC_SEX_CODE_FIELD_MISSING').toBeVisible();
    await expect(postalCodeInput, 'W1B_F2_E2E_REC_POSTAL_CODE_FIELD_MISSING').toBeVisible();
    await expect(addressInput, 'W1B_F2_E2E_REC_ADDRESS_FIELD_MISSING').toBeVisible();
    await expect(homePhoneInput, 'W1B_F2_E2E_REC_HOME_PHONE_FIELD_MISSING').toBeVisible();
    await expect(mobilePhoneInput, 'W1B_F2_E2E_REC_MOBILE_PHONE_FIELD_MISSING').toBeVisible();
    expect(await hasRequiredSemantics(nameInput), 'W1B_F2_E2E_REC_NAME_REQUIRED_SEMANTICS_MISSING').toBe(true);
    expect(
      await hasRequiredSemantics(birthDateInput),
      'W1B_F2_E2E_REC_BIRTH_DATE_REQUIRED_SEMANTICS_MISSING',
    ).toBe(true);
    expect(
      await hasRequiredSemantics(sexCodeSelect),
      'W1B_F2_E2E_REC_SEX_CODE_REQUIRED_SEMANTICS_MISSING',
    ).toBe(true);
    expect(
      await hasRequiredSemantics(postalCodeInput),
      'W1B_F2_E2E_REC_POSTAL_CODE_REQUIRED_SEMANTICS_FORBIDDEN',
    ).toBe(false);
    expect(
      await hasRequiredSemantics(addressInput),
      'W1B_F2_E2E_REC_ADDRESS_REQUIRED_SEMANTICS_FORBIDDEN',
    ).toBe(false);
    expect(
      await hasRequiredSemantics(homePhoneInput),
      'W1B_F2_E2E_REC_HOME_PHONE_REQUIRED_SEMANTICS_FORBIDDEN',
    ).toBe(false);
    expect(
      await hasRequiredSemantics(mobilePhoneInput),
      'W1B_F2_E2E_REC_MOBILE_PHONE_REQUIRED_SEMANTICS_FORBIDDEN',
    ).toBe(false);
    const sexOptionValues = await sexCodeSelect.locator('option').evaluateAll((options) =>
      options.map((option) => option.getAttribute('value') ?? '').sort(),
    );
    expect(sexOptionValues, 'W1B_F2_E2E_REC_SEX_CODE_PUBLIC_OPTION_SET_MISMATCH').toEqual(['FEMALE', 'MALE']);

    await nameInput.fill(syntheticRecipientCreate.name);
    await birthDateInput.fill(syntheticRecipientCreate.birth_date);
    await sexCodeSelect.selectOption(syntheticRecipientCreate.sex_code);
    await postalCodeInput.fill(syntheticRecipientCreate.postal_code);
    await addressInput.fill(syntheticRecipientCreate.address);
    await homePhoneInput.fill(syntheticRecipientCreate.home_phone);
    await mobilePhoneInput.fill(syntheticRecipientCreate.mobile_phone);

    const submitButton = page.getByTestId('recipient-submit-button');
    await expect(submitButton, 'W1B_F2_E2E_REC_SUBMIT_BUTTON_MISSING').toBeVisible();
    const postRequestPromise = page
      .waitForRequest(
        (request) =>
          new URL(request.url()).pathname === '/api/v1/recipients' && request.method() === 'POST',
        { timeout: 3000 },
      )
      .catch(() => null);
    await submitButton.click();
    const postRequest = await postRequestPromise;
    expect(postRequest, 'W1B_F2_E2E_REC_CREATE_POST_REQUEST_MISSING').not.toBeNull();
    if (!postRequest) return;
    const postBody = postRequest.postDataJSON() as Record<string, unknown>;
    expect(postBody, 'W1B_F2_E2E_REC_CREATE_POST_BODY_FIELDS_MISMATCH').toMatchObject(syntheticRecipientCreate);
    expect(
      Object.prototype.hasOwnProperty.call(postBody, 'recipient_no'),
      'W1B_F2_E2E_RECIPIENT_NO_CREATE_POST_KEY_FORBIDDEN',
    ).toBe(false);
    expect(postBody.home_phone, 'W1B_F2_E2E_REC_HOME_MOBILE_PAYLOAD_COLLISION').not.toBe(postBody.mobile_phone);
    expect(postBody.home_phone, 'W1B_F2_E2E_REC_HOME_PHONE_GUARDIAN_CONFUSION').not.toBe('010-0000-0003');
    expect(postBody.mobile_phone, 'W1B_F2_E2E_REC_MOBILE_PHONE_GUARDIAN_CONFUSION').not.toBe('010-0000-0003');
  });

  test('separates recipient and guardian phone inputs', async ({ page }) => {
    await mockRecipientContactReadback(page);
    await openRecipients(page);
    const recipientOption = page.getByTestId('recipient-name-option').first();
    await expect(recipientOption, 'W1B_F2_E2E_RECIPIENT_SELECTION_MISSING').toBeVisible();
    await recipientOption.click();
    await openRecipientCreate(page);
    await expect(page.getByTestId('recipient-home-phone-input'), 'W1B_F2_E2E_PHONE_RECIPIENT_HOME_FIELD_MISSING').toBeVisible();
    await expect(page.getByTestId('recipient-mobile-phone-input'), 'W1B_F2_E2E_PHONE_RECIPIENT_MOBILE_FIELD_MISSING').toBeVisible();
    const guardianPhoneInput = page.getByTestId('guardian-phone-input');
    await expect(guardianPhoneInput, 'W1B_F2_E2E_PHONE_GUARDIAN_FIELD_MISSING').toBeVisible();
    expect(
      await hasRequiredSemantics(guardianPhoneInput),
      'W1B_F2_E2E_GUARDIAN_PHONE_REQUIRED_SEMANTICS_FORBIDDEN',
    ).toBe(false);
    await expect(guardianPhoneInput, 'W1B_F2_E2E_GUARDIAN_PHONE_VALUE_MISSING').toHaveValue('010-0000-0003');

    const listSurface = page.getByTestId('recipient-list');
    await expect(listSurface, 'W1B_F2_E2E_CONTACT_LIST_SURFACE_MISSING').toBeVisible();
    await expect(page.getByTestId('recipient-list-home-phone'), 'W1B_F2_E2E_CONTACT_LIST_HOME_READBACK_MISSING').toHaveText(syntheticRecipientReadback.home_phone);
    await expect(page.getByTestId('recipient-list-mobile-phone'), 'W1B_F2_E2E_CONTACT_LIST_MOBILE_READBACK_MISSING').toHaveText(syntheticRecipientReadback.mobile_phone);
    await expect(page.getByTestId('recipient-list-address'), 'W1B_F2_E2E_CONTACT_LIST_ADDRESS_READBACK_MISSING').toHaveText(syntheticRecipientReadback.address);
    const listRecipientNo = page.getByTestId('recipient-list-recipient-no');
    await expect(listRecipientNo, 'W1B_F2_E2E_RECIPIENT_NO_LIST_SURFACE_MISSING').toBeVisible();
    await expect(listRecipientNo, 'W1B_F2_E2E_RECIPIENT_NO_LIST_UNASSIGNED_DISPLAY_MISSING').toHaveText(/^미부여$/);
    await expect(
      listSurface.locator(recipientNoNamedControlSelector),
      'W1B_F2_E2E_RECIPIENT_NO_LIST_NAMED_CONTROL_FORBIDDEN',
    ).toHaveCount(0);
    await expect(
      listSurface.locator(recipientNoCanonicalInputSelector),
      'W1B_F2_E2E_RECIPIENT_NO_LIST_CANONICAL_INPUT_FORBIDDEN',
    ).toHaveCount(0);
    await expect(
      listSurface.locator(recipientNoContenteditableSelector),
      'W1B_F2_E2E_RECIPIENT_NO_LIST_CONTENTEDITABLE_FORBIDDEN',
    ).toHaveCount(0);

    const nameOption = page.getByTestId('recipient-name-option');
    await expect(nameOption, 'W1B_F2_E2E_CONTACT_DETAIL_SELECTION_TARGET_MISSING').toBeVisible();
    await nameOption.click();
    const detailWorkspace = page.getByTestId('recipient-detail-workspace');
    await expect(detailWorkspace, 'W1B_F2_E2E_CONTACT_DETAIL_WORKSPACE_MISSING').toBeVisible();
    await expect(page.getByTestId('recipient-detail-home-phone'), 'W1B_F2_E2E_CONTACT_DETAIL_HOME_READBACK_MISSING').toHaveText(syntheticRecipientReadback.home_phone);
    await expect(page.getByTestId('recipient-detail-mobile-phone'), 'W1B_F2_E2E_CONTACT_DETAIL_MOBILE_READBACK_MISSING').toHaveText(syntheticRecipientReadback.mobile_phone);
    await expect(page.getByTestId('recipient-detail-address'), 'W1B_F2_E2E_CONTACT_DETAIL_ADDRESS_READBACK_MISSING').toHaveText(syntheticRecipientReadback.address);
    const detailRecipientNo = page.getByTestId('recipient-detail-recipient-no');
    await expect(detailRecipientNo, 'W1B_F2_E2E_RECIPIENT_NO_DETAIL_SURFACE_MISSING').toBeVisible();
    await expect(detailRecipientNo, 'W1B_F2_E2E_RECIPIENT_NO_DETAIL_UNASSIGNED_DISPLAY_MISSING').toHaveText(/^미부여$/);
    await expect(
      detailWorkspace.locator(recipientNoNamedControlSelector),
      'W1B_F2_E2E_RECIPIENT_NO_DETAIL_NAMED_CONTROL_FORBIDDEN',
    ).toHaveCount(0);
    await expect(
      detailWorkspace.locator(recipientNoCanonicalInputSelector),
      'W1B_F2_E2E_RECIPIENT_NO_DETAIL_CANONICAL_INPUT_FORBIDDEN',
    ).toHaveCount(0);
    await expect(
      detailWorkspace.locator(recipientNoContenteditableSelector),
      'W1B_F2_E2E_RECIPIENT_NO_DETAIL_CONTENTEDITABLE_FORBIDDEN',
    ).toHaveCount(0);
    await expect(page.getByTestId('recipient-detail-home-phone'), 'W1B_F2_E2E_CONTACT_DETAIL_GUARDIAN_CONFUSION').not.toHaveText('010-0000-0003');
  });

  test('shows guardian history and independent payer snapshot UI', async ({ page }) => {
    await mockRecipientContactReadback(page);
    await openRecipients(page);
    const recipientOption = page.getByTestId('recipient-name-option').first();
    await expect(recipientOption, 'W1B_F2_E2E_DETAIL_SELECTION_TARGET_MISSING').toBeVisible();
    await recipientOption.click();
    await expect(page.getByTestId('recipient-primary-guardian-history'), 'W1B_F2_E2E_PRIMARY_GUARDIAN_HISTORY_MISSING').toBeVisible();
    await expect(page.getByTestId('recipient-payer-snapshot-section'), 'W1B_F2_E2E_PAYER_SNAPSHOT_SECTION_MISSING').toBeVisible();
    await expect(page.getByTestId('recipient-payer-name-input'), 'W1B_F2_E2E_PAYER_NAME_SURFACE_MISSING').toBeVisible();
    await expect(page.getByTestId('recipient-payer-type-select'), 'W1B_F2_E2E_PAYER_TYPE_FORBIDDEN').toHaveCount(0);

    const payerMarkup = await page.getByTestId('recipient-payer-snapshot-section').innerHTML();
    expect(payerMarkup, 'W1B_F2_E2E_PAYER_TYPE_TOKEN_FORBIDDEN').not.toMatch(/payer_type/i);
    expect(payerMarkup, 'W1B_F2_E2E_PAYER_GUARDIAN_ROLE_TOKEN_FORBIDDEN').not.toMatch(/SELF|PRIMARY_GUARDIAN/i);
  });

  test('retains two-name selection, back navigation, search, and list context', async ({ page }) => {
    await mockSyntheticRecipientList(page);
    const listEntryUrl =
      '/recipients?search=TEST_RECIPIENT&filter=ACTIVE&sort=name_desc&page=2&selected=test-recipient-1';
    await openRecipients(page, listEntryUrl);

    const searchInput = page.getByTestId('recipient-search-input');
    await expect(searchInput, 'W1B_F2_E2E_SEARCH_SURFACE_MISSING').toBeVisible();
    await expect(searchInput, 'W1B_F2_E2E_LIST_SEARCH_STATE_MISSING').toHaveValue('TEST_RECIPIENT');

    const filterSelect = page.getByTestId('recipient-filter-select');
    await expect(filterSelect, 'W1B_F2_E2E_LIST_FILTER_CONTROL_MISSING').toBeVisible();
    await expect(filterSelect, 'W1B_F2_E2E_LIST_FILTER_STATE_MISSING').toHaveValue('ACTIVE');

    const sortSelect = page.getByTestId('recipient-sort-select');
    await expect(sortSelect, 'W1B_F2_E2E_LIST_SORT_CONTROL_MISSING').toBeVisible();
    await expect(sortSelect, 'W1B_F2_E2E_LIST_SORT_STATE_MISSING').toHaveValue('name_desc');

    const pageIndicator = page.getByTestId('recipient-page-indicator');
    await expect(pageIndicator, 'W1B_F2_E2E_LIST_PAGE_INDICATOR_MISSING').toHaveText('2');

    const listScroll = page.getByTestId('recipient-list-scroll');
    await expect(listScroll, 'W1B_F2_E2E_LIST_SCROLL_SURFACE_MISSING').toBeVisible();
    await listScroll.evaluate((element) => {
      element.style.height = '32px';
      element.style.maxHeight = '32px';
    });
    const scrollMetrics = await listScroll.evaluate((element) => ({
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
    }));
    expect(
      scrollMetrics.scrollHeight > scrollMetrics.clientHeight,
      'W1B_F2_E2E_LIST_SCROLL_OVERFLOW_MISSING',
    ).toBe(true);
    const retainedScrollTop = await listScroll.evaluate((element) => {
      const maxScrollTop = element.scrollHeight - element.clientHeight;
      element.scrollTop = Math.min(16, maxScrollTop);
      element.dispatchEvent(new Event('scroll', { bubbles: true }));
      return element.scrollTop;
    });
    expect(retainedScrollTop > 0, 'W1B_F2_E2E_LIST_SCROLL_SEED_FAILED').toBe(true);

    const nameOptions = page.getByTestId('recipient-name-option');
    await expect(nameOptions, 'W1B_F2_E2E_TWO_SYNTHETIC_NAMES_MISSING').toHaveCount(2);
    await expect(nameOptions.nth(0), 'W1B_F2_E2E_DESC_B_ROW_CONTEXT_MISSING').toContainText(syntheticRecipientNames[1]);
    await expect(nameOptions.nth(1), 'W1B_F2_E2E_DESC_A_ROW_CONTEXT_MISSING').toContainText(syntheticRecipientNames[0]);
    await expect(page.getByTestId('recipient-selected-name'), 'W1B_F2_E2E_A_SELECTION_CONTEXT_MISSING').toContainText(
      syntheticRecipientNames[0],
    );

    const listUrlBeforeB = page.url();
    await nameOptions
      .filter({ hasText: syntheticRecipientNames[1] })
      .evaluate((element) => (element as HTMLButtonElement).click());
    const detailWorkspace = page.getByTestId('recipient-detail-workspace');
    await expect(detailWorkspace, 'W1B_F2_E2E_DETAIL_WORKSPACE_MISSING').toBeVisible();
    await expect(detailWorkspace, 'W1B_F2_E2E_B_NAME_SELECTION_MISSING').toContainText(syntheticRecipientNames[1]);
    expect(page.url(), 'W1B_F2_E2E_DETAIL_HISTORY_ENTRY_MISSING').not.toBe(listUrlBeforeB);

    await page.goBack();
    await expect(page).toHaveURL(new RegExp('/recipients\\?search=TEST_RECIPIENT'));
    await expect(page.getByTestId('recipient-list'), 'W1B_F2_E2E_LIST_CONTEXT_NOT_RESTORED').toBeVisible();

    const restoredSearchInput = page.getByTestId('recipient-search-input');
    const restoredFilterSelect = page.getByTestId('recipient-filter-select');
    const restoredSortSelect = page.getByTestId('recipient-sort-select');
    const restoredPageIndicator = page.getByTestId('recipient-page-indicator');
    const restoredListScroll = page.getByTestId('recipient-list-scroll');
    await expect(restoredSearchInput, 'W1B_F2_E2E_BACK_SEARCH_CONTEXT_LOST').toHaveValue('TEST_RECIPIENT');
    await expect(restoredFilterSelect, 'W1B_F2_E2E_BACK_FILTER_CONTEXT_LOST').toHaveValue('ACTIVE');
    await expect(restoredSortSelect, 'W1B_F2_E2E_BACK_SORT_CONTEXT_LOST').toHaveValue('name_desc');
    await expect(restoredPageIndicator, 'W1B_F2_E2E_BACK_PAGE_CONTEXT_LOST').toHaveText('2');
    const restoredScrollTop = await restoredListScroll.evaluate((element) => element.scrollTop);
    expect(restoredScrollTop, 'W1B_F2_E2E_BACK_SCROLL_CONTEXT_LOST').toBe(retainedScrollTop);
    await expect(
      restoredListScroll.getByTestId('recipient-name-option'),
      'W1B_F2_E2E_BACK_VISIBLE_ROWS_CONTEXT_LOST',
    ).toHaveCount(2);
    await expect(
      restoredListScroll.getByTestId('recipient-name-option').nth(0),
      'W1B_F2_E2E_BACK_DESC_B_ROW_CONTEXT_LOST',
    ).toContainText(syntheticRecipientNames[1]);
    await expect(
      restoredListScroll.getByTestId('recipient-name-option').nth(1),
      'W1B_F2_E2E_BACK_DESC_A_ROW_CONTEXT_LOST',
    ).toContainText(syntheticRecipientNames[0]);
    await expect(
      page.getByTestId('recipient-selected-name'),
      'W1B_F2_E2E_BACK_SELECTION_CONTEXT_LOST',
    ).toContainText(syntheticRecipientNames[0]);
  });

  test('does not open a popup when selecting a recipient name', async ({ page }) => {
    let popupCount = 0;
    page.on('popup', (popup) => {
      popupCount += 1;
      void popup.close();
    });

    await mockSyntheticRecipientList(page);
    await openRecipients(page);
    const nameOption = page.getByTestId('recipient-name-option').first();
    await expect(nameOption, 'W1B_F2_E2E_POPUP_ZERO_SELECTION_TARGET_MISSING').toBeVisible();
    await nameOption.click();
    expect(popupCount, 'W1B_F2_E2E_POPUP_ZERO_CONTRACT_BROKEN').toBe(0);
  });

  test('requires the recipient surface before evaluating ABS absence checks', async ({ page }) => {
    await openRecipients(page);
    const recipientSurface = page.getByTestId('recipient-list');
    await expect(recipientSurface, 'W1B_F2_E2E_ABS_SURFACE_MISSING_FALSE_GREEN_GUARD').toBeVisible();
    await expect(recipientSurface, 'W1B_F2_E2E_ABS_LEGACY_FIELD_LEAK').not.toContainText(/legacy_|payer_type|guardian_id/i);
    await expect(recipientSurface, 'W1B_F2_E2E_ABS_MONTHLY_SCHEDULE_PLACEHOLDER').not.toContainText(/월간 일정|팝업|window\.open/i);
    await expect(recipientSurface, 'W1B_F2_E2E_ABS_FAKE_RECIPIENT_CONTRACT_ROW').not.toContainText(
      /인정번호|장기요양|서비스 그룹|계약|방문요양|방문목욕|L1234567890|3등급/i,
    );
  });
});
