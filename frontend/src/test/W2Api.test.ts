import './setup';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  W2ConflictError,
  closeOfficialWorkCard,
  createPersonalTodo,
  createSchedule,
  createServicePlanNotice,
  deletePersonalTodo,
  deleteSchedule,
  finalizeScheduleMonth,
  listOfficialWorkCards,
  listPersonalTodos,
  listSchedules,
  listServicePlanNotices,
  normalizeOfficialWorkCardCollection,
  normalizeServicePlanNoticeHistory,
  reorderPersonalTodos,
  replaceSchedule,
  replaceServicePlanNotice,
  updatePersonalTodo,
} from '../services/w2Api';

const originalFetch = globalThis.fetch;

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function officialResponse() {
  return {
    as_of_date: '2026-08-13',
    groups: [{
      staff_id: 11,
      staff_name: '박복지',
      items: [{
        id: 3,
        row_version: 4,
        kind: 'CONTRACT_EXPIRY',
        display: {
          work_title: '계약만료',
          target_name: '   ',
          detail: '계약 갱신',
          due_date: '2026-09-30',
          d_day: 48,
        },
      }],
    }],
  };
}

function todoResponse(revision = 6) {
  return {
    list_revision: revision,
    items: [{
      id: 2,
      title: '둘',
      completed: false,
      sort_order: 0,
      row_version: revision,
    }],
  };
}

function scheduleResponse(version = 5) {
  return {
    schedule_month: '2026-08-01',
    finalized: false,
    finalized_at_utc: null,
    row_version: version,
    items: [{
      id: 9,
      schedule_month: '2026-08-01',
      recipient_id: 10,
      assigned_staff: [{ staff_id: 11, employment_id: 21 }],
      service_type_id: 12,
      starts_at_utc: '2026-08-10T00:00:00Z',
      ends_at_utc: '2026-08-10T01:00:00Z',
      row_version: 2,
    }],
  };
}

function servicePlanResponse(version = 3) {
  return {
    items: [{
      id: 31,
      recipient_id: 10,
      recipient_contract_id: 22,
      notification_date: '2026-08-10',
      applied_start_date: '2026-09-01',
      applied_end_date: '2027-06-30',
      invalidated_at_utc: null,
      replacement_service_plan_notice_id: null,
      row_version: version,
    }],
  };
}

describe('W2 API adapter', () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => { globalThis.fetch = originalFetch; });

  it('normalizes the exact grouped official-card response and five display fields', () => {
    const result = normalizeOfficialWorkCardCollection(officialResponse());
    expect(result).toEqual({
      asOfDate: '2026-08-13',
      groups: [{
        staffId: 11,
        staffName: '박복지',
        cards: [{
          id: 3,
          rowVersion: 4,
          kind: 'CONTRACT_EXPIRY',
          title: '계약만료',
          targetName: '미입력',
          detail: '계약 갱신',
          dueDate: '2026-09-30',
          dDay: 48,
        }],
      }],
    });
    expect(() => normalizeOfficialWorkCardCollection({ items: [] })).toThrow(
      /official-work-card-list.as_of_date/,
    );
  });

  it('uses grouped official-card read and close responses with expected_row_version', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(officialResponse()))
      .mockResolvedValueOnce(json({ ...officialResponse(), groups: [] }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await listOfficialWorkCards();
    const closed = await closeOfficialWorkCard(3, 8);

    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/official-work-cards');
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/official-work-cards/3/close');
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({
      expected_row_version: 8,
    });
    expect(closed.groups).toEqual([]);
  });

  it('sends todo list revision and row version on every mutation and full ordered_ids', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(todoResponse(6)))
      .mockResolvedValueOnce(json(todoResponse(7)))
      .mockResolvedValueOnce(json(todoResponse(8)))
      .mockResolvedValueOnce(json(todoResponse(9)))
      .mockResolvedValueOnce(json(todoResponse(10)));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    expect((await listPersonalTodos()).listRevision).toBe(6);
    await createPersonalTodo(' 새 할 일 ', 6);
    await updatePersonalTodo({ id: 2, rowVersion: 7 }, 7, { completed: true });
    await deletePersonalTodo({ id: 2, rowVersion: 8 }, 8);
    await reorderPersonalTodos([4, 2, 7], 9);

    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({
      title: '새 할 일',
      expected_list_revision: 6,
    });
    expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toEqual({
      expected_list_revision: 7,
      expected_row_version: 7,
      completed: true,
    });
    expect(fetchMock.mock.calls[3][1]?.method).toBe('DELETE');
    expect(JSON.parse(String(fetchMock.mock.calls[3][1]?.body))).toEqual({
      expected_list_revision: 8,
      expected_row_version: 8,
    });
    expect(JSON.parse(String(fetchMock.mock.calls[4][1]?.body))).toEqual({
      expected_list_revision: 9,
      ordered_ids: [4, 2, 7],
    });
  });

  it('reads todo 409 details.latest as the full server list', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(json({
      error: { code: 'ROW_VERSION_CONFLICT', message: '먼저 변경됨' },
      details: { latest: todoResponse(12) },
    }, 409)) as unknown as typeof fetch;

    const promise = updatePersonalTodo({ id: 2, rowVersion: 6 }, 6, { completed: true });
    await expect(promise).rejects.toBeInstanceOf(W2ConflictError);
    await expect(promise).rejects.toMatchObject({
      latestTodoList: { listRevision: 12, items: [{ id: 2, rowVersion: 12 }] },
    });
  });

  it('queries schedules with only month and optional recipient_id or staff_id', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(scheduleResponse()))
      .mockResolvedValueOnce(json(scheduleResponse()));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await listSchedules({ month: '2026-08-01', recipientId: 10 });
    await listSchedules({ month: '2026-08-01', staffId: 11 });

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/v1/schedules?month=2026-08-01&recipient_id=10',
    );
    expect(fetchMock.mock.calls[1][0]).toBe(
      '/api/v1/schedules?month=2026-08-01&staff_id=11',
    );
    const queriedUrls = fetchMock.mock.calls.map((call) => String(call[0])).join('\n');
    expect(queriedUrls).not.toContain('projection');
    expect(queriedUrls).not.toContain('staff_kind');
  });

  it('sends the exact schedule create payload and consumes the returned month snapshot', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(scheduleResponse(6)));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const result = await createSchedule({
      scheduleMonth: '2026-08-01',
      recipientId: 10,
      assignedStaff: [{ staffId: 11, employmentId: 21 }],
      serviceTypeId: 12,
      startsAtUtc: '2026-08-10T00:00:00.000Z',
      endsAtUtc: '2026-08-10T01:00:00.000Z',
      expectedMonthRowVersion: 5,
    });

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      schedule_month: '2026-08-01',
      recipient_id: 10,
      assigned_staff: [{ staff_id: 11, employment_id: 21 }],
      service_type_id: 12,
      starts_at_utc: '2026-08-10T00:00:00.000Z',
      ends_at_utc: '2026-08-10T01:00:00.000Z',
      expected_month_row_version: 5,
    });
    expect(result).toMatchObject({ scheduleMonth: '2026-08-01', rowVersion: 6 });
  });

  it('uses PUT for replace without schedule_month and DELETE with both versions', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(scheduleResponse(7)))
      .mockResolvedValueOnce(json(scheduleResponse(8)));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await replaceSchedule(9, {
      recipientId: 10,
      assignedStaff: [{ staffId: 11, employmentId: 21 }],
      serviceTypeId: 12,
      startsAtUtc: '2026-08-10T00:00:00.000Z',
      endsAtUtc: '2026-08-10T01:00:00.000Z',
      expectedMonthRowVersion: 5,
      expectedRowVersion: 2,
    });
    await deleteSchedule(9, {
      expectedMonthRowVersion: 7,
      expectedRowVersion: 3,
    });

    expect(fetchMock.mock.calls[0][1]?.method).toBe('PUT');
    const replaceBody = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(replaceBody).toEqual({
      expected_month_row_version: 5,
      expected_row_version: 2,
      recipient_id: 10,
      assigned_staff: [{ staff_id: 11, employment_id: 21 }],
      service_type_id: 12,
      starts_at_utc: '2026-08-10T00:00:00.000Z',
      ends_at_utc: '2026-08-10T01:00:00.000Z',
    });
    expect(replaceBody).not.toHaveProperty('schedule_month');
    expect(fetchMock.mock.calls[1][1]?.method).toBe('DELETE');
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({
      expected_month_row_version: 7,
      expected_row_version: 3,
    });
  });

  it('finalizes the exact schedule-month endpoint with expected_month_row_version', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({
      ...scheduleResponse(6),
      finalized: true,
    }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const result = await finalizeScheduleMonth('2026-08-01', 5);
    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/v1/schedule-months/2026-08-01/finalize',
    );
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      expected_month_row_version: 5,
    });
    expect(result.finalized).toBe(true);
  });

  it('reads schedule 409 details.latest without replacing caller draft data', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(json({
      error: { code: 'ROW_VERSION_CONFLICT', message: '먼저 저장됨' },
      details: { latest: scheduleResponse(11) },
    }, 409)) as unknown as typeof fetch;

    const promise = replaceSchedule(9, {
      recipientId: 10,
      assignedStaff: [{ staffId: 11, employmentId: 21 }],
      serviceTypeId: 12,
      startsAtUtc: '2026-08-10T00:00:00.000Z',
      endsAtUtc: '2026-08-10T01:00:00.000Z',
      expectedMonthRowVersion: 10,
      expectedRowVersion: 1,
    });

    await expect(promise).rejects.toBeInstanceOf(W2ConflictError);
    await expect(promise).rejects.toMatchObject({
      latestScheduleSnapshot: {
        scheduleMonth: '2026-08-01',
        rowVersion: 11,
        items: [{ id: 9, serviceTypeId: 12 }],
      },
    });
  });

  it('normalizes and calls the service-plan notice history and create endpoints', async () => {
    expect(normalizeServicePlanNoticeHistory(servicePlanResponse())).toMatchObject({
      items: [{
        id: 31,
        recipientId: 10,
        recipientContractId: 22,
        notificationDate: '2026-08-10',
        appliedStartDate: '2026-09-01',
        appliedEndDate: '2027-06-30',
        rowVersion: 3,
      }],
    });

    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(servicePlanResponse()))
      .mockResolvedValueOnce(json(servicePlanResponse(1).items[0]));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await listServicePlanNotices(10);
    await createServicePlanNotice(10, {
      recipientContractId: 22,
      notificationDate: '2026-08-10',
      appliedStartDate: '2026-09-01',
      appliedEndDate: null,
    });

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/v1/recipients/10/service-plan-notices',
    );
    expect(fetchMock.mock.calls[1][1]?.method).toBe('POST');
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({
      recipient_contract_id: 22,
      notification_date: '2026-08-10',
      applied_start_date: '2026-09-01',
      applied_end_date: null,
    });
  });

  it('keeps service-plan draft ownership with the caller and exposes latest on 409', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({
      error: { code: 'ROW_VERSION_CONFLICT', message: '먼저 변경됨' },
      details: { latest: servicePlanResponse(8) },
    }, 409));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const promise = replaceServicePlanNotice(10, 31, 3, {
      recipientContractId: 22,
      notificationDate: '2026-08-11',
      appliedStartDate: '2026-09-02',
    });

    await expect(promise).rejects.toBeInstanceOf(W2ConflictError);
    await expect(promise).rejects.toMatchObject({
      latestServicePlanHistory: {
        items: [{ id: 31, rowVersion: 8 }],
      },
    });
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      recipient_contract_id: 22,
      notification_date: '2026-08-11',
      applied_start_date: '2026-09-02',
      expected_row_version: 3,
    });
  });
});
