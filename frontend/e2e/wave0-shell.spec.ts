import { expect, test } from 'playwright/test';

const menuLabels = [
  '대시보드',
  '수급자',
  '직원',
  '사회복지사',
  '본인부담금',
  '입출력',
  '파일함',
  '설정',
];

test.beforeEach(async ({ context }) => {
  await context.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/bootstrap/status') {
      await route.fulfill({ json: { bootstrap_required: false } });
      return;
    }
    if (path === '/api/auth/me') {
      await route.fulfill({
        json: {
          account: { id: 1, display_name: '합성 관리자', role_code: 'ADMIN' },
        },
      });
      return;
    }
    if (path === '/api/v1/official-work-cards') {
      await route.fulfill({ json: { as_of_date: '2026-08-15', groups: [] } });
      return;
    }
    if (path.startsWith('/api/v1/schedules')) {
      await route.fulfill({
        json: {
          schedule_month: '2026-08-01',
          finalized: false,
          finalized_at_utc: null,
          row_version: 1,
          items: [],
        },
      });
      return;
    }
    await route.fulfill({ status: 404, json: { detail: { code: 'not_found' } } });
  });
});

test('social-worker schedule launcher uses the current accessible control', async ({ page }) => {
  await page.goto('/social-workers');

  await expect(page.getByTestId('page-social-workers')).toBeVisible();
  const openButton = page.getByRole('button', { name: '사회복지사 일정표 열기' });
  await expect(openButton).toBeVisible();
  await expect(page.getByRole('button', { name: '수급자 일정표 열기' })).toBeVisible();
  await expect(page.getByRole('button', { name: '요양보호사 일정표 열기' })).toBeVisible();

  const popupPromise = page.waitForEvent('popup');
  await openButton.click();
  const popup = await popupPromise;
  await expect(popup).toHaveURL(/\/schedules\/social-worker\?month=\d{4}-\d{2}$/);
  await expect(popup.getByTestId('schedule-popup-social-worker')).toBeVisible();
  await popup.close();
});

test('dashboard exposes the current official work-card surface', async ({ page }) => {
  await page.goto('/dashboard');

  await expect(page.getByTestId('page-dashboard')).toBeVisible();
  await expect(page.getByRole('region', { name: '공식 업무카드' })).toBeVisible();
  await expect(page.getByText('열린 업무카드가 없습니다.')).toBeVisible();
  await expect(page.getByTestId('dashboard-work-card')).toHaveCount(0);
});

test('Wave 0 desktop shell exposes the canonical navigation', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByTestId('app-shell')).toBeVisible();
  await expect(page.getByTestId('app-header')).toBeVisible();

  const sidebar = page.getByTestId('app-sidebar');
  for (const label of menuLabels) {
    await expect(sidebar.getByText(label, { exact: true })).toBeVisible();
  }

  await sidebar.getByText('직원', { exact: true }).click();
  await expect(page).toHaveURL(/\/staff$/);
  await expect(page.getByTestId('page-staff')).toBeVisible();
});

for (const viewport of [
  { width: 1440, height: 1000, name: 'dashboard' },
  { width: 1366, height: 768, name: 'notebook' },
]) {
  test(`shell remains usable at ${viewport.name} resolution`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto('/dashboard');

    await expect(page.getByTestId('app-sidebar')).toBeVisible();
    await expect(page.getByTestId('app-content')).toBeVisible();
    const hasHorizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(hasHorizontalOverflow).toBe(false);
  });
}
