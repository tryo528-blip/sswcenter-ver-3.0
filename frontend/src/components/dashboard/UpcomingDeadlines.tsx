import { useEffect, useMemo, useState } from 'react';
import type { RecipientDeadlineItem } from '../../services/recipientApi';
import { computeDday } from './deadlines';

export const UPCOMING_DEADLINE_PAGE_SIZE = 15;

function deadlineKindLabel(kind: RecipientDeadlineItem['kind']): string {
  switch (kind) {
    case 'CERTIFICATION_EXPIRY':
      return '인정 만료';
    case 'CONTRACT_EXPIRY':
      return '계약 만료';
    case 'PLAN_RENEWAL':
      return '계획서 갱신';
    default:
      return kind;
  }
}

export function UpcomingDeadlines({ items }: { items: readonly RecipientDeadlineItem[] }) {
  const [page, setPage] = useState(0);
  const pageCount = Math.max(1, Math.ceil(items.length / UPCOMING_DEADLINE_PAGE_SIZE));

  useEffect(() => {
    setPage((current) => Math.min(current, pageCount - 1));
  }, [pageCount]);

  const visibleItems = useMemo(
    () => items.slice(
      page * UPCOMING_DEADLINE_PAGE_SIZE,
      (page + 1) * UPCOMING_DEADLINE_PAGE_SIZE,
    ),
    [items, page],
  );

  return (
    <section className="dashboard-rail-card dashboard-deadline-card" aria-label="다가오는 마감일">
      <h3>다가오는 마감일</h3>
      <div className="dashboard-deadline-list">
        {visibleItems.length === 0 ? (
          <p className="dashboard-deadline-empty">등록된 수급자 마감일이 없습니다.</p>
        ) : (
          visibleItems.map((item) => (
            <div
              className="dashboard-deadline-row"
              key={`${item.kind}-${item.recipient_id}-${item.source_id}`}
            >
              <strong>{computeDday(new Date(), item.due_date).dday}</strong>
              <span className="dashboard-deadline-body">
                <span className="dashboard-deadline-date">{item.due_date}</span>
                <span className="dashboard-deadline-detail">
                  {`${item.recipient_name?.trim() || '미입력'} · ${deadlineKindLabel(item.kind)}`}
                </span>
              </span>
            </div>
          ))
        )}
      </div>
      {items.length > UPCOMING_DEADLINE_PAGE_SIZE && (
        <nav className="dashboard-deadline-pagination" aria-label="마감일 페이지">
          <button type="button" disabled={page === 0} onClick={() => setPage((value) => value - 1)}>
            이전
          </button>
          <span>{page + 1} / {pageCount}</span>
          <button
            type="button"
            disabled={page + 1 >= pageCount}
            onClick={() => setPage((value) => value + 1)}
          >
            다음
          </button>
        </nav>
      )}
    </section>
  );
}
