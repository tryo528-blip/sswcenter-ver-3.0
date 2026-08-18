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
  recipient_status: 'ACTIVE',
  recipient_no: null,
  memo: null,
  postal_code: null,
  address: null,
  home_phone: null,
  mobile_phone: '010-1234-5678',
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
    if (url.pathname === `${base}/detail-batch` && method === 'POST') {
      const rawBody = request.postData() ?? '';
      const parsedBody = JSON.parse(
        rawBody.replace(/"amount_krw":([0-9]+)/, '"amount_krw":"$1"'),
      ) as {
        certification_identity?: Record<string, unknown>;
        benefit_period?: { payload: Record<string, unknown> };
        approval_amount_period?: { payload: Record<string, unknown> };
      };
      const savedSections: string[] = [];
      if (parsedBody.certification_identity) {
        state.identity = {
          recipient_id: 42,
          certification_number: 'L1234567890',
          row_version: 1,
        };
        savedSections.push('certification_identity');
      }
      if (parsedBody.benefit_period) {
        state.benefits = [
          {
            id: 1,
            recipient_id: 42,
            ...parsedBody.benefit_period.payload,
            invalidated_at_utc: null,
            replacement_benefit_period_id: null,
            row_version: 1,
          },
        ];
        savedSections.push('benefit_period');
      }
      if (parsedBody.approval_amount_period) {
        const amount = String(parsedBody.approval_amount_period.payload.amount_krw);
        const createdJson = JSON.stringify({
          id: 9,
          recipient_id: 42,
          ...parsedBody.approval_amount_period.payload,
          amount_krw: null,
          invalidated_at_utc: null,
          replacement_local_approval_amount_period_id: null,
          row_version: 1,
        }).replace('"amount_krw":null', `"amount_krw":${amount}`);
        state.approvalListJson = `{"items":[${createdJson}]}`;
        savedSections.push('approval_amount_period');
      }
      await route.fulfill({
        json: { recipient_id: 42, saved_sections: savedSections },
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
  await page.getByTestId('recipient-detail-toggle').click();
  await expect(page.getByTestId('w1c-panel')).toBeVisible();
}

test('W1C browser surface preserves exact options and forbidden absences', async ({
  page,
}) => {
  await installW1cApi(page);
  await openW1cPanel(page);

  const gradeValues = await page
    .getByTestId('w1c-certification-grade-select')
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
  await page.getByTestId('recipient-basic-edit').click();
  await expect(page.getByTestId('recipient-detail-batch-toolbar')).toBeVisible();

  await page.getByTestId('w1c-certification-input').fill('l1234567890-100');
  await expect(page.getByTestId('w1c-certification-preview')).toContainText(
    'L1234567890',
  );
  await page.getByTestId('w1c-benefit-select').selectOption('MEDICAL_9');
  await page.getByTestId('w1c-benefit-start-text').fill('2026-07-15');
  await page
    .getByTestId('recipient-detail-batch-toolbar')
    .getByRole('button', { name: '저장' })
    .click();
  await expect(page.getByTestId('w1c-certification-section')).toContainText(
    'L1234567890',
  );
  await expect(page.getByTestId('w1c-benefit-history')).toContainText('MEDICAL_9');

  const detailBatchPost = state.requests.find((request) => {
    const url = new URL(request.url());
    return (
      request.method() === 'POST' &&
      url.pathname === '/api/v1/recipients/42/detail-batch'
    );
  });
  expect(detailBatchPost?.postDataJSON()).toEqual({
    certification_identity: {
      certification_number: 'l1234567890-100',
    },
    benefit_period: {
      payload: {
        benefit_code: 'MEDICAL_9',
        start_text: '2026-07-15',
      },
    },
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
  await page.getByTestId('recipient-basic-edit').click();
  await expect(page.getByTestId('recipient-detail-batch-toolbar')).toBeVisible();

  await expect(page.getByTestId('w1c-approval-history')).toContainText(
    '9,223,372,036,854,775,807원',
  );
  await page
    .getByTestId('w1c-approval-amount-input')
    .fill('9223372036854775807');
  await page.getByTestId('w1c-approval-start-date').fill('2026-08-01');
  await page
    .getByTestId('recipient-detail-batch-toolbar')
    .getByRole('button', { name: '저장' })
    .click();

  const detailBatchPost = state.requests.find((request) => {
    const url = new URL(request.url());
    return (
      request.method() === 'POST' &&
      url.pathname === '/api/v1/recipients/42/detail-batch'
    );
  });
  expect(detailBatchPost?.postData()).toContain(
    '"amount_krw":9223372036854775807',
  );
  expect(detailBatchPost?.postData()).not.toContain(
    '"amount_krw":"9223372036854775807"',
  );
  await expect(page.getByTestId('w1c-approval-history')).toContainText(
    '9,223,372,036,854,775,807원',
  );
});
