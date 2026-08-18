import { expect, test, type Page } from 'playwright/test';

test.use({ screenshot: 'off', trace: 'off', video: 'off' });

const PIN = process.env.SSWCENTER_W2_E2E_PIN ?? '';

async function login(page: Page): Promise<void> {
  await page.goto('/dashboard');
  const loading = page.getByTestId('auth-loading');
  await expect(loading, 'W2_BROWSER_AUTH_LOADING_STUCK').toBeHidden({ timeout: 20_000 });
  const loginContainer = page.getByTestId('login-container');
  await expect(loginContainer, 'W2_BROWSER_REAL_LOGIN_REQUIRED').toBeVisible();
  await expect(page.locator('.dev-bypass-banner'), 'W2_BROWSER_DEV_BYPASS_FORBIDDEN').toHaveCount(0);
  const responsePromise = page.waitForResponse(
    (response) => new URL(response.url()).pathname === '/api/auth/login'
      && response.request().method() === 'POST',
  );
  await page.getByTestId('login-pin-input').fill(PIN);
  const submit = page.getByTestId('login-submit-btn');
  if (await submit.count()) await submit.click();
  const response = await responsePromise;
  expect(response.ok(), `W2_BROWSER_LOGIN_FAILED:${response.status()}`).toBe(true);
  await expect(page.getByTestId('page-dashboard'), 'W2_BROWSER_DASHBOARD_MISSING').toBeVisible({
    timeout: 20_000,
  });
}

async function openReassign(page: Page) {
  const card = page.getByTestId('official-work-card');
  await expect(card, 'W2_BROWSER_CARD_MISSING').toHaveCount(1);
  await card.getByTestId('official-work-card-reassign').click();
  const dialog = page.getByTestId('official-work-card-reassign-dialog');
  await expect(dialog, 'W2_BROWSER_DIALOG_MISSING').toBeVisible();
  const select = dialog.getByTestId('official-work-card-new-assignee');
  await expect(select, 'W2_BROWSER_CANDIDATES_NOT_READY').toBeEnabled();
  return { card, dialog, select };
}

test('ADMIN reassigns one real DB card and a stale page consumes 409 latest', async ({
  page,
  context,
}) => {
  expect(process.env.SSWCENTER_W2_REAL_E2E, 'W2_BROWSER_WRAPPER_REQUIRED').toBe('1');
  expect(PIN, 'W2_BROWSER_PIN_REQUIRED').toMatch(/^\d{6}$/);
  expect(process.env.VITE_DEV_LOGIN_BYPASS, 'W2_BROWSER_BYPASS_MUST_BE_FALSE').toBe('false');

  const pageErrors: string[] = [];
  const serverErrors: string[] = [];
  const observe = (target: Page) => {
    target.on('pageerror', (error) => pageErrors.push(error.message));
    target.on('response', (response) => {
      if (response.url().includes('/api/') && response.status() >= 500) {
        serverErrors.push(`${response.status()} ${new URL(response.url()).pathname}`);
      }
    });
  };
  observe(page);
  await login(page);

  const stalePage = await context.newPage();
  observe(stalePage);
  try {
    await stalePage.goto('/dashboard');
    await expect(stalePage.getByTestId('page-dashboard')).toBeVisible({ timeout: 20_000 });

    const first = await openReassign(page);
    const stale = await openReassign(stalePage);

    expect(await first.dialog.locator('dt').allTextContents(), 'W2_BROWSER_CONFIRM_FIELDS').toEqual([
      '업무종류',
      '대상자',
      '상세업무',
      '마감일',
      '현재 담당자',
    ]);
    await expect(first.dialog).toContainText('계획서통보');
    await expect(first.dialog).toContainText('김순자');
    await expect(first.dialog).toContainText('급여계획서 갱신 통보 브라우저 검증');
    await expect(first.dialog).toContainText('2026-08-20');
    await expect(first.dialog).toContainText('강태현');
    await expect(first.select.getByRole('option', { name: '강태현' })).toHaveCount(0);
    await expect(first.select.getByRole('option', { name: '정소연' })).toHaveCount(1);
    await expect(page.getByRole('button', { name: '닫기' })).toHaveCount(0);

    await first.select.selectOption({ label: '정소연' });
    await first.dialog.getByTestId('official-work-card-reassign-confirm').click();
    await expect(first.dialog).toBeHidden();
    await expect(page.getByText('정소연', { exact: true })).toBeVisible();
    await expect(page.getByTestId('official-work-card')).toContainText('김순자');

    await stale.select.selectOption({ label: '정소연' });
    const conflictPromise = stalePage.waitForResponse(
      (response) => response.request().method() === 'POST'
        && /\/api\/v1\/official-work-cards\/\d+\/reassign$/.test(new URL(response.url()).pathname),
    );
    const candidateReloadPromise = stalePage.waitForResponse(
      (response) => response.request().method() === 'GET'
        && new URL(response.url()).pathname === '/api/v1/official-work-cards/eligible-assignees',
    );
    await stale.dialog.getByTestId('official-work-card-reassign-confirm').click();
    const conflict = await conflictPromise;
    expect(conflict.status(), 'W2_BROWSER_STALE_MUST_BE_409').toBe(409);
    const candidateReload = await candidateReloadPromise;
    expect(
      candidateReload.ok(),
      `W2_BROWSER_CANDIDATE_RELOAD_FAILED:${candidateReload.status()}`,
    ).toBe(true);
    await expect(stale.dialog, 'W2_BROWSER_STALE_DIALOG_MUST_REMAIN').toBeVisible();
    await expect(
      stale.dialog.getByRole('status'),
      'W2_BROWSER_CANDIDATE_RELOAD_NOT_SETTLED',
    ).toHaveCount(0);
    const currentAssigneeValue = stale.dialog
      .getByText('현재 담당자', { exact: true })
      .locator('..')
      .locator('dd');
    await expect(
      currentAssigneeValue,
      'W2_BROWSER_LATEST_ASSIGNEE_MISMATCH',
    ).toHaveText('정소연');
    await expect(stale.select, 'W2_BROWSER_RELOADED_SELECT_DISABLED').toBeEnabled();
    await expect(stale.select, 'W2_BROWSER_STALE_SELECTION_NOT_CLEARED').toHaveValue('');
    await expect(stale.select.getByRole('option', { name: '정소연' })).toHaveCount(0);
    await expect(stale.select.getByRole('option', { name: '강태현' })).toHaveCount(1);
    await expect(
      stale.dialog.getByTestId('official-work-card-reassign-confirm'),
      'W2_BROWSER_CONFIRM_MUST_STAY_DISABLED',
    ).toBeDisabled();
    await expect(stale.dialog.getByRole('alert'), 'W2_BROWSER_CONFLICT_ALERT_MISSING').toBeVisible();
    await expect(stalePage.getByRole('button', { name: '닫기' })).toHaveCount(0);
  } finally {
    await stalePage.close();
  }

  expect(pageErrors, 'W2_BROWSER_PAGE_ERRORS').toEqual([]);
  expect(serverErrors, 'W2_BROWSER_SERVER_ERRORS').toEqual([]);
  // Exact marker consumed by the owner harness.
  // eslint-disable-next-line no-console
  console.log('W2_OFFICIAL_CARD_BROWSER_GREEN');
});
