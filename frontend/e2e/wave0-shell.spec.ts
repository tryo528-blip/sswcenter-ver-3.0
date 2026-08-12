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
    await route.fulfill({ status: 404, json: { detail: { code: 'not_found' } } });
  });
});

test('schedule launcher exposes the three people-based calendars', async ({ page }) => {
  await page.goto('/dashboard');

  await page.getByTestId('header-btn-new-schedule').click();
  const scheduleMenu = page.getByRole('menu', { name: '일정표 종류' });
  await expect(scheduleMenu.getByRole('menuitem')).toHaveText([
    '수급자',
    '요양보호사',
    '사회복지사',
  ]);

  const popupPromise = page.waitForEvent('popup');
  await scheduleMenu.getByRole('menuitem', { name: '사회복지사' }).click();
  const popup = await popupPromise;
  await expect(popup).toHaveURL(/\/schedules\/social-worker\?month=\d{4}-\d{2}$/);
  await expect(popup.getByTestId('schedule-popup-social-worker')).toBeVisible();
  await popup.close();
});

test('mission cards can be reordered by dragging', async ({ page }) => {
  await page.goto('/dashboard');

  const cards = page.getByTestId('dashboard-work-card');
  await expect(cards).toHaveCount(2);
  const firstHandle = page.getByRole('button', { name: '홍길동 수급자 임무카드 이동' });
  const source = await firstHandle.boundingBox();
  const target = await cards.nth(1).boundingBox();
  expect(source).not.toBeNull();
  expect(target).not.toBeNull();
  if (!source || !target) return;
  await page.mouse.move(source.x + source.width / 2, source.y + source.height / 2);
  await page.mouse.down();
  await page.mouse.move(target.x + target.width / 2, target.y + target.height / 2, { steps: 12 });
  await page.mouse.up();

  await expect(cards.nth(0)).toHaveAttribute('data-card-id', 'staff-onboarding');
  await expect(cards.nth(1)).toHaveAttribute('data-card-id', 'recipient-renewal');
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
