import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import '../App.css';
import { OfficialWorkCards } from '../components/dashboard/OfficialWorkCards';
import { UpcomingDeadlines } from '../components/dashboard/UpcomingDeadlines';
import { useAuthSafe } from '../context/useAuth';
import { listRecipientDeadlines, listRecipients } from '../services/recipientApi';
import type { RecipientDeadlineItem } from '../services/recipientApi';
import { fetchAllStaff } from '../services/staffApi';
import {
  closeOfficialWorkCard,
  listOfficialWorkCards,
  type OfficialWorkCard,
  type OfficialWorkCardCollection,
} from '../services/w2Api';

const staffTasks = [
  ['보수교육', '1nn/1mm'],
  ['직원상담', '1nn/1mm'],
  ['인권교육', '1nn/1mm'],
  ['연간교육', '1nn/1mm'],
  ['건강검진', '1nn/1mm'],
  ['신규교육', '1nn명'],
] as const;

const recipientTasks = [
  ['상담반영', '1nn/1mm'],
  ['반기평가', '1nn/1mm'],
  ['서류미비', '1nn건'],
  ['인정만료', '1nn건'],
  ['계약만료', '1nn건'],
] as const;

const EMPTY_WORK_CARDS: OfficialWorkCardCollection = {
  asOfDate: '',
  groups: [],
};

function SummaryCard({
  title,
  personCount,
  linkTo,
  tasks,
}: {
  title: string;
  personCount: string;
  linkTo: string;
  tasks: readonly (readonly [string, string])[];
}) {
  return (
    <section className="dashboard-summary-card">
      <div className="dashboard-summary-heading">
        <div className="dashboard-summary-title">
          <h2><Link to={linkTo} className="dashboard-summary-link">{title}</Link></h2>
        </div>
        <p className="dashboard-summary-count">{personCount}</p>
      </div>
      <div className="dashboard-task-grid">
        {tasks.map(([label, count]) => (
          <div className="dashboard-task-row" key={label}>
            <span>{label}</span>
            <span className="dashboard-task-count">{count}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function errorMessage(error: unknown): string | null {
  if (!(error instanceof Error)) return '오류가 발생했습니다.';
  if (error.name === 'AbortError') return null;
  return error.message || '오류가 발생했습니다.';
}

export const DashboardPage = () => {
  const { user } = useAuthSafe();
  const isAdmin = user?.role_code === 'ADMIN';
  const [staffCount, setStaffCount] = useState<number | null>(null);
  const [recipientCount, setRecipientCount] = useState<number | null>(null);
  const [recipientDeadlines, setRecipientDeadlines] = useState<RecipientDeadlineItem[]>([]);
  const [workCards, setWorkCards] = useState<OfficialWorkCardCollection>(EMPTY_WORK_CARDS);
  const [closingId, setClosingId] = useState<number | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);

  useEffect(() => {
    const abortController = new AbortController();
    const { signal } = abortController;
    let active = true;

    async function loadDashboard() {
      setApiError(null);
      const [staffResult, recipientResult, deadlineResult, cardResult] = await Promise.allSettled([
        fetchAllStaff(signal),
        listRecipients({ pageSize: 1, signal }),
        listRecipientDeadlines(signal),
        listOfficialWorkCards(signal),
      ]);
      if (!active || signal.aborted) return;

      const errors: string[] = [];
      if (staffResult.status === 'fulfilled') setStaffCount(staffResult.value.total);
      else {
        const message = errorMessage(staffResult.reason);
        if (message) errors.push(message);
      }

      if (recipientResult.status === 'fulfilled') setRecipientCount(recipientResult.value.total);
      else {
        const message = errorMessage(recipientResult.reason);
        if (message) errors.push(message);
      }

      if (deadlineResult.status === 'fulfilled') setRecipientDeadlines(deadlineResult.value.items);
      else {
        const message = errorMessage(deadlineResult.reason);
        if (message) errors.push(message);
      }

      if (cardResult.status === 'fulfilled') setWorkCards(cardResult.value);
      else {
        const message = errorMessage(cardResult.reason);
        if (message) errors.push(message);
      }

      if (errors.length > 0) setApiError([...new Set(errors)].join('; '));
    }

    void loadDashboard();
    return () => {
      active = false;
      abortController.abort();
    };
  }, [user?.id]);

  const closeCard = async (card: OfficialWorkCard) => {
    if (isAdmin || closingId !== null) return;
    setClosingId(card.id);
    setApiError(null);
    try {
      setWorkCards(await closeOfficialWorkCard(card.id, card.rowVersion));
    } catch (error) {
      setApiError(errorMessage(error));
    } finally {
      setClosingId(null);
    }
  };

  return (
    <div className="dashboard-page" data-testid="page-dashboard">
      <h1 className="visually-hidden">대시보드</h1>
      {apiError && <div className="dashboard-api-error" role="alert">{apiError}</div>}
      <div className="dashboard-content-grid dashboard-content-grid-w2">
        <div className="dashboard-summary-grid">
          <SummaryCard
            title="직원"
            personCount={staffCount !== null ? `${staffCount}명` : '…'}
            linkTo="/staff"
            tasks={staffTasks}
          />
          <SummaryCard
            title="수급자"
            personCount={recipientCount !== null ? `${recipientCount}명` : '…'}
            linkTo="/recipients"
            tasks={recipientTasks}
          />
        </div>

        <div className="dashboard-top-rail">
          <UpcomingDeadlines items={recipientDeadlines} />
        </div>

        <OfficialWorkCards
          closingId={closingId}
          collection={workCards}
          onClose={(card) => void closeCard(card)}
          readOnly={isAdmin}
          showStaffGroups={isAdmin}
        />
      </div>
    </div>
  );
};

export default DashboardPage;
