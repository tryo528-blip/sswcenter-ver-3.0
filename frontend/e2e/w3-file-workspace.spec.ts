import { expect, test, type BrowserContext } from 'playwright/test';

type RunStatus = 'PREVIEW_READY' | 'CONFIRMED' | 'APPLIED';

function workspace(status?: RunStatus, reviewPending = false) {
  if (status === undefined) {
    return {
      source_type: 'RFID',
      target_date: '2026-07-06',
      active: null,
      latest_run: null,
      recent_runs: [],
    };
  }
  const run = {
    id: 31,
    source_type: 'RFID',
    target_date: '2026-07-06',
    original_filename: 'w3-pseudonymous.xlsx',
    parser_profile_version: 'rfid-xlsx-v1',
    status,
    row_version: status === 'PREVIEW_READY' ? (reviewPending ? 1 : 2) : status === 'CONFIRMED' ? 3 : 4,
    preview_digest: 'a'.repeat(64),
    warning_codes: ['EXPORT_CONTAINS_OTHER_DATES'],
    counts: {
      raw_rows: 1,
      normalized_rows: 1,
      target_rows: 1,
      derived_groups: 0,
      auto_matches: 0,
      manual_matches: reviewPending ? 0 : 1,
      review_pending: reviewPending ? 1 : 0,
      blocked: 0,
    },
    decisions: reviewPending ? [{
      id: 51,
      source_occurrence_identity: 'pseudonymous-occurrence-1',
      status: 'REVIEW_PENDING',
      reason_code: 'SOURCE_STABLE_KEY_MISSING',
      source_row_number: 174,
      service_date: '2026-07-06',
      service_category: '방문요양',
      event_state: 'START_ONLY',
      end_display: '종료X · 11:27',
      row_version: 1,
    }] : [{
      id: 52,
      source_occurrence_identity: 'pseudonymous-occurrence-1',
      status: 'MANUAL_MATCH',
      reason_code: 'USER_VALIDATED_TYPED_LINK',
      source_row_number: 174,
      service_date: '2026-07-06',
      service_category: '방문요양',
      event_state: 'START_ONLY',
      end_display: '종료X · 11:27',
      row_version: 2,
    }],
    created_at_utc: '2026-08-18T06:00:00Z',
    can_confirm: status === 'PREVIEW_READY' && !reviewPending,
    can_apply: status === 'CONFIRMED',
  };
  return {
    source_type: 'RFID',
    target_date: '2026-07-06',
    active: status === 'APPLIED' ? {
      snapshot_id: 21,
      import_run_id: 31,
      source_type: 'RFID',
      target_date: '2026-07-06',
      row_version: 2,
    } : null,
    latest_run: run,
    recent_runs: [run],
  };
}

async function installRoutes(context: BrowserContext) {
  let current = workspace();
  let multipartBoundarySeen = false;

  await context.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === '/api/bootstrap/status') {
      await route.fulfill({ json: { bootstrap_required: false } });
      return;
    }
    if (path === '/api/auth/me') {
      await route.fulfill({
        json: { account: { id: 1, display_name: '가명 관리자', role_code: 'ADMIN' } },
      });
      return;
    }
    if (path === '/api/v1/w3/workspace' && request.method() === 'GET') {
      await route.fulfill({ json: current });
      return;
    }
    if (path === '/api/v1/w3/import-runs' && request.method() === 'POST') {
      multipartBoundarySeen = /^multipart\/form-data; boundary=/.test(
        request.headers()['content-type'] ?? '',
      );
      current = workspace('PREVIEW_READY', true);
      await route.fulfill({ status: 201, json: current });
      return;
    }
    if (path.endsWith('/decisions/51/resolve') && request.method() === 'POST') {
      const payload = request.postDataJSON();
      expect(payload).toMatchObject({
        expected_run_row_version: 1,
        recipient_id: 7,
        certification_period_id: 7,
        staff_id: 7,
        employment_id: 7,
        service_type_id: 7,
        recipient_contract_id: 7,
        care_assignment_id: 7,
        w2_schedule_id: 7,
      });
      expect(payload.command_idempotency_key).toMatch(/^w3-resolve-/);
      current = workspace('PREVIEW_READY', false);
      await route.fulfill({ json: current });
      return;
    }
    if (path.endsWith('/31/confirm') && request.method() === 'POST') {
      const payload = request.postDataJSON();
      expect(payload.expected_row_version).toBe(2);
      expect(payload.preview_digest).toBe('a'.repeat(64));
      current = workspace('CONFIRMED');
      await route.fulfill({ json: current });
      return;
    }
    if (path.endsWith('/31/apply') && request.method() === 'POST') {
      const payload = request.postDataJSON();
      expect(payload.expected_row_version).toBe(3);
      current = workspace('APPLIED');
      await route.fulfill({ json: current });
      return;
    }
    await route.fulfill({ status: 404, json: { detail: { code: 'not_found' } } });
  });
  return {
    multipartBoundarySeen: () => multipartBoundarySeen,
  };
}

test('FILE_ONLY workspace completes one stateful flow at 390px without page overflow', async ({
  context,
  page,
}) => {
  const evidence = await installRoutes(context);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/io');

  await expect(page.getByText('선택한 날짜의 파일을 올리면')).toBeVisible();
  await page.getByLabel('대상 일자').fill('2026-07-06');
  await page.getByLabel('엑셀 파일').setInputFiles({
    name: 'w3-pseudonymous.xlsx',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: Buffer.from('pseudonymous xlsx fixture'),
  });
  await page.getByRole('button', { name: '파일 분석' }).click();

  await expect(page.getByText('종료X · 11:27')).toBeVisible();
  await expect(page.getByText('EXPORT_CONTAINS_OTHER_DATES')).toBeVisible();
  await expect(page.getByText('검토 항목을 모두 연결해야')).toBeVisible();
  await expect(page.getByRole('button', { name: '미리보기 확인' })).toBeDisabled();
  await expect(page.getByRole('button', { name: '업무자료 적용' })).toBeDisabled();
  await expect(page.getByText(/OCR/i)).toHaveCount(0);
  expect(evidence.multipartBoundarySeen()).toBe(true);

  await page.getByRole('button', { name: '연결 입력' }).click();
  for (const label of [
    '수급자 ID',
    '인정기간 ID',
    '직원 ID',
    '재직 ID',
    '서비스유형 ID',
    '계약 ID',
    '배정 ID',
    '일정 ID',
  ]) {
    await page.getByLabel(label).fill('7');
  }
  await page.getByRole('button', { name: '수동 연결 저장' }).click();
  await expect(page.getByText('검토 항목을 수동 연결했습니다.')).toBeVisible();

  await page.getByRole('button', { name: '미리보기 확인' }).click();
  await expect(page.getByText('미리보기를 확인했습니다.')).toBeVisible();
  await page.getByRole('button', { name: '업무자료 적용' }).click();
  await expect(page.getByText('업무자료 적용이 완료되었습니다.')).toBeVisible();
  await expect(page.getByText('현재 적용본')).toBeVisible();
  await expect(page.getByText('스냅샷 #21')).toBeVisible();
  await expect(page.getByText('실행 #31')).toBeVisible();

  const documentOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(documentOverflow).toBe(false);
  const primaryCommands = page.locator('.io-action-buttons');
  await expect(primaryCommands).toBeVisible();
  const box = await primaryCommands.boundingBox();
  expect(box).not.toBeNull();
  expect((box?.x ?? 391) + (box?.width ?? 0)).toBeLessThanOrEqual(390);
});
