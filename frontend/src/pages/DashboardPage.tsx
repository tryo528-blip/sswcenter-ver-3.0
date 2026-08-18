import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import '../App.css';
import {
  OfficialWorkCardReassignDialog,
  OfficialWorkCards,
} from '../components/dashboard/OfficialWorkCards';
import { UpcomingDeadlines } from '../components/dashboard/UpcomingDeadlines';
import { useAuthSafe } from '../context/useAuth';
import { listRecipientDeadlines, listRecipients } from '../services/recipientApi';
import type { RecipientDeadlineItem } from '../services/recipientApi';
import { fetchAllStaff } from '../services/staffApi';
import {
  closeOfficialWorkCard,
  listOfficialWorkCardEligibleAssignees,
  listOfficialWorkCards,
  reassignOfficialWorkCard,
  W2ConflictError,
  type OfficialWorkCard,
  type OfficialWorkCardCollection,
  type OfficialWorkCardEligibleAssignee,
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
  const [reassigningId, setReassigningId] = useState<number | null>(null);
  const [reassignCard, setReassignCard] = useState<OfficialWorkCard | null>(null);
  const [eligibleAssignees, setEligibleAssignees] = useState<
    readonly OfficialWorkCardEligibleAssignee[]
  >([]);
  const [selectedAssigneeId, setSelectedAssigneeId] = useState<number | ''>('');
  const [reassignError, setReassignError] = useState<string | null>(null);
  const [reassignLoading, setReassignLoading] = useState(false);
  const [reassignNotice, setReassignNotice] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const eligibleRequestGeneration = useRef(0);
  const eligibleAbortController = useRef<AbortController | null>(null);
  const reassignTrigger = useRef<HTMLButtonElement | null>(null);
  const restoreReassignFocus = useRef(false);

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

  useEffect(() => () => {
    eligibleAbortController.current?.abort();
  }, []);

  useEffect(() => {
    if (reassignCard !== null || !restoreReassignFocus.current) return;
    restoreReassignFocus.current = false;
    const trigger = reassignTrigger.current;
    if (trigger?.isConnected) trigger.focus();
  }, [reassignCard]);

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

  const cancelEligibleRequest = () => {
    eligibleRequestGeneration.current += 1;
    eligibleAbortController.current?.abort();
    eligibleAbortController.current = null;
  };

  const dismissReassign = (notice?: string) => {
    cancelEligibleRequest();
    restoreReassignFocus.current = true;
    setReassignCard(null);
    setEligibleAssignees([]);
    setSelectedAssigneeId('');
    setReassignError(null);
    setReassignLoading(false);
    if (notice) setReassignNotice(notice);
  };

  const loadEligibleAssignees = async (
    card: OfficialWorkCard,
    preserveSelection: number | '' = '',
    keepError = false,
  ) => {
    cancelEligibleRequest();
    const generation = eligibleRequestGeneration.current + 1;
    eligibleRequestGeneration.current = generation;
    const controller = new AbortController();
    eligibleAbortController.current = controller;
    setEligibleAssignees([]);
    setSelectedAssigneeId('');
    setReassignLoading(true);
    if (!keepError) setReassignError(null);
    try {
      const eligible = await listOfficialWorkCardEligibleAssignees(controller.signal);
      if (controller.signal.aborted || generation !== eligibleRequestGeneration.current) return;
      const choices = eligible.items.filter((item) => item.staffId !== card.assigneeStaffId);
      setEligibleAssignees(eligible.items);
      setSelectedAssigneeId(
        preserveSelection !== '' && choices.some((item) => item.staffId === preserveSelection)
          ? preserveSelection
          : '',
      );
    } catch (error) {
      if (controller.signal.aborted || generation !== eligibleRequestGeneration.current) return;
      setEligibleAssignees([]);
      setSelectedAssigneeId('');
      setReassignError(errorMessage(error) || '담당자 목록을 불러오지 못했습니다.');
    } finally {
      if (generation === eligibleRequestGeneration.current) setReassignLoading(false);
    }
  };

  const openReassign = (card: OfficialWorkCard, trigger: HTMLButtonElement) => {
    if (!isAdmin || reassigningId !== null) return;
    reassignTrigger.current = trigger;
    restoreReassignFocus.current = false;
    setReassignCard(card);
    setReassignNotice(null);
    setApiError(null);
    void loadEligibleAssignees(card);
  };

  const confirmReassign = async () => {
    const card = reassignCard;
    const selected = selectedAssigneeId;
    const isEligible = (
      selected !== ''
      && selected !== card?.assigneeStaffId
      && eligibleAssignees.some((item) => item.staffId === selected)
    );
    if (
      !isAdmin
      || card === null
      || !isEligible
      || reassignLoading
      || reassigningId !== null
    ) {
      if (card !== null && !reassignLoading) {
        setReassignError('현재 담당자가 아닌 새 담당자를 선택하세요.');
      }
      return;
    }
    setReassigningId(card.id);
    setReassignError(null);
    try {
      setWorkCards(await reassignOfficialWorkCard(
        card.id,
        card.rowVersion,
        selected,
      ));
      dismissReassign();
    } catch (error) {
      if (error instanceof W2ConflictError && error.latestOfficialWorkCards) {
        setWorkCards(error.latestOfficialWorkCards);
        const latestCard = error.latestOfficialWorkCards.groups
          .flatMap((group) => group.cards)
          .find((item) => item.id === card.id);
        if (!latestCard) {
          dismissReassign('해당 업무카드는 이미 완료되었습니다. 목록을 새로고침했습니다.');
          return;
        }
        setReassignCard(latestCard);
        setReassignError(errorMessage(error));
        void loadEligibleAssignees(latestCard, selected, true);
        return;
      }
      setReassignError(errorMessage(error));
    } finally {
      setReassigningId(null);
    }
  };

  return (
    <div className="dashboard-page" data-testid="page-dashboard">
      <h1 className="visually-hidden">대시보드</h1>
      {apiError && <div className="dashboard-api-error" role="alert">{apiError}</div>}
      {reassignNotice && <div className="dashboard-reassign-notice" role="status">{reassignNotice}</div>}
      <div
        aria-hidden={reassignCard ? true : undefined}
        className="dashboard-content-grid dashboard-content-grid-w2"
        inert={reassignCard ? true : undefined}
      >
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
          canReassign={isAdmin}
          closingId={closingId}
          collection={workCards}
          onClose={(card) => void closeCard(card)}
          onReassign={(card, trigger) => openReassign(card, trigger)}
          readOnly={isAdmin}
          reassigningId={reassigningId}
          showStaffGroups={isAdmin}
        />
      </div>
      {isAdmin && reassignCard && (
        <OfficialWorkCardReassignDialog
          card={reassignCard}
          currentAssigneeName={reassignCard.assigneeStaffName}
          eligibleAssignees={eligibleAssignees}
          error={reassignError}
          loading={reassignLoading}
          onCancel={() => dismissReassign()}
          onConfirm={() => void confirmReassign()}
          onSelectedStaffIdChange={setSelectedAssigneeId}
          selectedStaffId={selectedAssigneeId}
          submitting={reassigningId === reassignCard.id}
        />
      )}
    </div>
  );
};

export default DashboardPage;
