import { expect, test, type Page, type Request } from 'playwright/test';

test.use({
  trace: 'off',
  video: 'off',
  screenshot: 'off',
});

const recipient = {
  id: 42,
  name: 'W1C 브라우저 수급자',
  birth_date: '1950-01-01',
  sex_code: 'FEMALE',
  recipient_no: null,
  memo: null,
  postal_code: null,
  address: null,
  home_phone: null,
  mobile_phone: null,
  row_version: 1,
};

type BrowserState = {
  identity: Record<string, unknown> | null;
  benefits: Array<Record<string, unknown>>;
  approvalListJson: string;
  requests: Request[];
};

async function installW1cApi(page: Page): Promise<BrowserState> {
  const state: BrowserState = {
    identity: null,
    benefits: [],
    approvalListJson: '{"items":[]}',
    requests: [],
  };
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    state.requests.push(request);
    const base = '/api/v1/recipients/42';

    if (url.pathname === '/api/bootstrap/status') {
      await route.fulfill({ json: { bootstrap_required: false } });
      return;
    }
    if (url.pathname === '/api/auth/me') {
      await route.fulfill({
        json: {
          account: { id: 1, display_name: 'W1C 관리자', role_code: 'ADMIN' },
        },
      });
      return;
    }
    if (url.pathname === '/api/v1/recipients' && method === 'GET') {
      await route.fulfill({
        json: { items: [recipient], total: 1, page: 1, page_size: 100 },
      });
      return;
    }
    if (url.pathname === base && method === 'GET') {
      await route.fulfill({ json: recipient });
      return;
    }
    if (
      method === 'GET' &&
      [
        `${base}/guardians`,
        `${base}/primary-guardian-periods`,
        `${base}/payer-snapshots`,
        `${base}/certification-periods`,
        `${base}/grade-periods`,
      ].includes(url.pathname)
    ) {
      await route.fulfill({ json: { items: [] } });
      return;
    }
    if (url.pathname === `${base}/certification-identity` && method === 'GET') {
      if (state.identity) {
        await route.fulfill({ json: state.identity });
      } else {
        await route.fulfill({
          status: 404,
          json: {
            error: {
              code: 'CERTIFICATION_IDENTITY_NOT_FOUND',
              message: '인정 본번호가 등록되지 않았습니다.',
              field_errors: [],
              details: {},
            },
          },
        });
      }
      return;
    }
    if (url.pathname === `${base}/certification-identity` && method === 'POST') {
      state.identity = {
        recipient_id: 42,
        certification_number: 'L1234567890',
        row_version: 1,
      };
      await route.fulfill({ status: 201, json: state.identity });
      return;
    }
    if (url.pathname === `${base}/benefit-periods` && method === 'GET') {
      await route.fulfill({ json: { items: state.benefits } });
      return;
    }
    if (url.pathname === `${base}/benefit-periods` && method === 'POST') {
      const payload = request.postDataJSON() as Record<string, unknown>;
      const created = {
        id: 1,
        recipient_id: 42,
        ...payload,
        invalidated_at_utc: null,
        replacement_benefit_period_id: null,
        row_version: 1,
      };
      state.benefits = [created];
      await route.fulfill({ status: 201, json: created });
      return;
    }
    if (url.pathname === `${base}/approval-amount-periods` && method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: state.approvalListJson,
      });
      return;
    }
    if (url.pathname === `${base}/approval-amount-periods` && method === 'POST') {
      const rawBody = request.postData() ?? '';
      const amountMatch = rawBody.match(/"amount_krw":([0-9]+)/);
      if (!amountMatch) {
        await route.fulfill({ status: 422, json: { error: { code: 'VALIDATION_ERROR' } } });
        return;
      }
      const parsedBody = JSON.parse(
        rawBody.replace(
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
      state.approvalListJson = `{"items":[${createdJson}]}`;
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: createdJson,
      });
      return;
    }
    await route.fulfill({
      status: 404,
      json: { error: { code: 'NOT_FOUND', message: 'not found' } },
    });
  });
  return state;
}

async function openW1cPanel(page: Page): Promise<void> {
  await page.goto('/recipients');
  await page.getByTestId('recipient-name-option').click();
  await expect(page.getByTestId('w1c-panel')).toBeVisible();
}

test('W1C browser surface preserves exact options and forbidden absences', async ({
  page,
}) => {
  await installW1cApi(page);
  await openW1cPanel(page);

  const gradeValues = await page
    .getByTestId('w1c-grade-select')
    .locator('option')
    .evaluateAll((options) => options.map((option) => option.getAttribute('value')));
  expect(gradeValues).toEqual(['1', '2', '3', '4', '5']);

  const benefit = page.getByTestId('w1c-benefit-select');
  const benefitValues = await benefit
    .locator('option')
    .evaluateAll((options) => options.map((option) => option.getAttribute('value')));
  expect(benefitValues).toEqual([
    '',
    'GENERAL',
    'BASIC_LIVELIHOOD',
    'REDUCTION_6',
    'REDUCTION_9',
    'MEDICAL_6',
    'MEDICAL_9',
  ]);
  await expect(benefit).toHaveValue('');
  await expect(page.getByTestId('w1c-benefit-empty')).toContainText(
    '적용 혜택 자료가 없습니다.',
  );
  await expect(
    page.locator(
      '[name="issued_date"], [name="grade_changed_date"], [name="benefit_rate"], [name="monthly_maximum"]',
    ),
  ).toHaveCount(0);
  await expect(page.getByText('인지지원등급')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /GENERAL|일반.*자동/ })).toHaveCount(0);
});

test('W1C browser submits suffix input and an explicitly selected benefit', async ({
  page,
}) => {
  const state = await installW1cApi(page);
  await openW1cPanel(page);

  await page.getByTestId('w1c-certification-input').fill('l1234567890-100');
  await expect(page.getByTestId('w1c-certification-preview')).toContainText(
    'L1234567890',
  );
  await page.getByRole('button', { name: '인정 본번호 등록' }).click();
  await expect(page.getByTestId('w1c-certification-section')).toContainText(
    'L1234567890',
  );

  await page.getByTestId('w1c-benefit-select').selectOption('MEDICAL_9');
  await page.getByTestId('w1c-benefit-start-date').fill('2026-07-15');
  await page.getByRole('button', { name: '혜택기간 등록' }).click();
  await expect(page.getByTestId('w1c-benefit-history')).toContainText('MEDICAL_9');

  const identityPost = state.requests.find((request) => {
    const url = new URL(request.url());
    return (
      request.method() === 'POST' &&
      url.pathname === '/api/v1/recipients/42/certification-identity'
    );
  });
  expect(identityPost?.postDataJSON()).toEqual({
    certification_number: 'l1234567890-100',
  });
  const benefitPost = state.requests.find((request) => {
    const url = new URL(request.url());
    return (
      request.method() === 'POST' &&
      url.pathname === '/api/v1/recipients/42/benefit-periods'
    );
  });
  expect(benefitPost?.postDataJSON()).toEqual({
    benefit_code: 'MEDICAL_9',
    start_date: '2026-07-15',
    end_date: null,
  });
});

test('W1C browser preserves bigint maximum through GET, POST, and UI', async ({
  page,
}) => {
  const state = await installW1cApi(page);
  state.approvalListJson =
    '{"items":[{"id":8,"recipient_id":42,"amount_krw":9223372036854775807,' +
    '"start_date":"2026-07-01","end_date":null,"invalidated_at_utc":null,' +
    '"replacement_local_approval_amount_period_id":null,"row_version":1}]}';
  await openW1cPanel(page);

  await expect(page.getByTestId('w1c-approval-history')).toContainText(
    '9,223,372,036,854,775,807원',
  );
  await page
    .getByTestId('w1c-approval-amount-input')
    .fill('9223372036854775807');
  await page.getByTestId('w1c-approval-start-date').fill('2026-08-01');
  await page.getByRole('button', { name: '승인금액 기간 등록' }).click();

  const approvalPost = state.requests.find((request) => {
    const url = new URL(request.url());
    return (
      request.method() === 'POST' &&
      url.pathname === '/api/v1/recipients/42/approval-amount-periods'
    );
  });
  expect(approvalPost?.postData()).toContain(
    '"amount_krw":9223372036854775807',
  );
  expect(approvalPost?.postData()).not.toContain(
    '"amount_krw":"9223372036854775807"',
  );
  await expect(page.getByTestId('w1c-approval-history')).toContainText(
    '9,223,372,036,854,775,807원',
  );
});
