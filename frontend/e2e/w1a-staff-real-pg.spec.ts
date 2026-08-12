import { expect, test, type Page } from 'playwright/test';

// Disable trace, video, and screenshot for sensitive Playwright tests per Plan §8
test.use({
  trace: 'off',
  video: 'off',
  screenshot: 'off',
});

const rrnSuffixByProject: Record<string, string> = {
  'chromium-1440x1000': '56',
  'chromium-1440x900': '57',
  'chromium-1366x768': '58',
};

const buildSyntheticRrn = (suffix: string) => "90010" + "1-11234" + suffix;
const buildSyntheticPin = () => "1234" + "56";

async function expectNoHorizontalOverflow(page: Page, marker: string): Promise<void> {
  const hasOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(hasOverflow, marker).toBe(false);
}

test.describe('W1A Staff Vertical Slice Real PG E2E', () => {
  test('bootstrap, login, staff registration, employment close, re-hire, list context retention, and RRN reveal', async ({ page, request }, testInfo) => {
    const rrnSuffix = rrnSuffixByProject[testInfo.project.name];
    expect(rrnSuffix, 'W1A_E2E_VIEWPORT_PROJECT_UNKNOWN').toBeTruthy();
    const syntheticRrn = buildSyntheticRrn(rrnSuffix);
    const syntheticPin = buildSyntheticPin();
    const staffName = `합성 직원 ${rrnSuffix}`;
    let popupCount = 0;
    page.on('popup', (popup) => {
      popupCount += 1;
      void popup.close();
    });

    // 1. Perform bootstrap if required via API
    const statusRes = await request.get('/api/bootstrap/status');
    expect(statusRes.ok(), 'W1A_E2E_BOOTSTRAP_STATUS_FAILED').toBe(true);

    const statusData = await statusRes.json();
    if (statusData.bootstrap_required) {
      const bootstrapRes = await request.post('/api/bootstrap', {
        data: {
          center_name: '테스트 센터',
          admin_name: '관리자',
          birth_date: '1980-01-01',
          sex_code: 'MALE',
          start_date: '2026-01-01',
          pin: syntheticPin,
        },
      });
      expect(bootstrapRes.ok(), 'W1A_E2E_BOOTSTRAP_FAILED').toBe(true);
    }

    // 2. Navigate and log in through the real browser context. The isolated
    // Playwright request fixture does not share its cookie jar with the page.
    await page.goto('/staff');
    await expect(page.getByTestId('login-container')).toBeVisible();
    await page.getByTestId('login-pin-input').fill(syntheticPin);
    const legacyLoginSubmit = page.getByTestId('login-submit-btn');
    if (await legacyLoginSubmit.count()) await legacyLoginSubmit.click();

    // Route absence assertion check
    await expect(
      page.getByTestId('page-staff'),
      'W1A_E2E_ROUTE_MISSING: /staff workspace element page-staff not found',
    ).toBeVisible();
    await expectNoHorizontalOverflow(page, 'W1A_E2E_SHELL_HORIZONTAL_OVERFLOW');

    // 3. Set list context before opening the registration form.
    const searchInput = page.getByLabel('직원 검색', { exact: true });
    await searchInput.fill(staffName);
    await page.getByRole('button', { name: '검색', exact: true }).click();

    // 4. Open new staff registration form
    const registerButton = page.getByRole('button', { name: /신규 직원 등록/i });
    await expect(registerButton).toBeVisible();
    await registerButton.click();

    // 5. Fill synthetic form data
    await page.getByLabel(/성명/i).fill(staffName);
    await page.getByLabel(/생년월일/i).fill('1990-01-01');
    await page.getByLabel(/성별/i).selectOption('MALE');
    await page.getByLabel(/주민등록번호/i).fill(syntheticRrn);
    await page.getByLabel(/전화번호/i).fill('010-1234-5678');
    await page.getByLabel(/입사일/i).fill('2026-01-01');

    const createResponsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith('/api/v1/staff') &&
        response.request().method() === 'POST',
    );
    const submitButton = page.getByRole('button', { name: '등록', exact: true });
    await submitButton.click();
    const createResponse = await createResponsePromise;
    let createErrorCode = 'NONE';
    if (!createResponse.ok()) {
      const errorBody = await createResponse.json().catch(() => null);
      createErrorCode = errorBody?.error?.code ?? 'NON_JSON';
    }
    expect(
      createResponse.ok(),
      `W1A_E2E_CREATE_FAILED:${createResponse.status()}:${createErrorCode}`,
    ).toBe(true);
    const createdBody = await createResponse.json();
    const createdStaffId = Number(createdBody.id);
    const firstEmploymentId = Number(createdBody.current_employment?.id);
    expect(Number.isSafeInteger(createdStaffId), 'W1A_E2E_STAFF_ID_INVALID').toBe(true);
    expect(
      Number.isSafeInteger(firstEmploymentId),
      'W1A_E2E_FIRST_EMPLOYMENT_ID_INVALID',
    ).toBe(true);

    // 6. Verify staff created and masked RRN displayed in detail workspace
    await expect(page.getByTestId('staff-detail-workspace')).toBeVisible();
    await expect(page.getByText('900101-*******')).toBeVisible();
    await expect(page.getByText(`직원 #${createdStaffId}`)).toBeVisible();
    await expect(searchInput).toHaveValue(staffName);
    await expectNoHorizontalOverflow(page, 'W1A_E2E_DETAIL_HORIZONTAL_OVERFLOW');

    // 7. Close employment
    const closeEmploymentButton = page.getByRole('button', { name: /재직 종료/i });
    await closeEmploymentButton.click();
    await page.getByLabel(/퇴사일/i).fill('2026-05-31');
    const closeResponsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith('/close') &&
        response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: /종료 확정/i }).click();
    const closeResponse = await closeResponsePromise;
    expect(
      closeResponse.ok(),
      `W1A_E2E_CLOSE_FAILED:${closeResponse.status()}`,
    ).toBe(true);

    // 8. Re-hire same staff member
    const rehireButton = page.getByRole('button', { name: /재입사/i });
    await rehireButton.click();
    await page.getByLabel(/재입사일/i).fill('2026-06-01');
    const rehireResponsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/v1/staff/${createdStaffId}/employments`) &&
        response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: /재입사 등록/i }).click();
    const rehireResponse = await rehireResponsePromise;
    expect(
      rehireResponse.ok(),
      `W1A_E2E_REHIRE_FAILED:${rehireResponse.status()}`,
    ).toBe(true);
    const rehireBody = await rehireResponse.json();
    expect(rehireBody.staff_id, 'W1A_E2E_REHIRE_STAFF_ID_CHANGED').toBe(
      createdStaffId,
    );
    expect(rehireBody.id, 'W1A_E2E_REHIRE_EMPLOYMENT_ID_REUSED').not.toBe(
      firstEmploymentId,
    );
    expect(rehireBody.employment_no, 'W1A_E2E_REHIRE_NUMBER_INVALID').toBe(2);

    await expect(page.getByTestId('staff-employment-list')).toContainText('2026-06-01');
    await expect(page.getByText(`직원 #${createdStaffId}`)).toBeVisible();
    await expect(searchInput).toHaveValue(staffName);
    await expectNoHorizontalOverflow(page, 'W1A_E2E_REHIRE_HORIZONTAL_OVERFLOW');

    // 9. Reveal RRN with current PIN
    const revealButton = page.getByRole('button', { name: /주민번호 보기/i });
    await revealButton.click();

    await page.getByPlaceholder(/현재 비밀번호|PIN/i).fill(syntheticPin);
    const revealResponsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith(
          `/api/v1/staff/${createdStaffId}/sensitive-identity/reveal`,
        ) && response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: /확인|조회/i }).click();
    const revealResponse = await revealResponsePromise;
    expect(
      revealResponse.ok(),
      `W1A_E2E_REVEAL_FAILED:${revealResponse.status()}`,
    ).toBe(true);
    expect(
      revealResponse.headers()['cache-control'],
      'W1A_E2E_REVEAL_CACHE_CONTROL_MISSING',
    ).toContain('no-store');

    // Evaluate match as boolean to avoid printing sensitive string in failure output
    const revealedText = await page.getByTestId('revealed-rrn').textContent();
    const isRevealMatch = revealedText === syntheticRrn;
    expect(isRevealMatch, 'W1A_E2E_REVEAL_MISMATCH').toBe(true);
    await expectNoHorizontalOverflow(page, 'W1A_E2E_REVEAL_HORIZONTAL_OVERFLOW');

    // Close reveal modal and verify plaintext is removed from DOM
    await page
      .getByTestId('revealed-rrn')
      .locator('..')
      .getByRole('button', { name: '닫기', exact: true })
      .click();
    await expect(page.getByTestId('revealed-rrn')).toHaveCount(0);
    const plaintextRemainsInDom = await page
      .locator('body')
      .innerText()
      .then((bodyText) => bodyText.includes(syntheticRrn));
    expect(plaintextRemainsInDom, 'W1A_E2E_RRN_REMAINS_IN_DOM').toBe(false);
    expect(popupCount, 'W1A_E2E_UNEXPECTED_POPUP').toBe(0);
  });
});
